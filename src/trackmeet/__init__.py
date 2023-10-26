# SPDX-License-Identifier: MIT
"""Timing and data handling application wrapper for track events."""

import sys
import gi
import logging
import metarace
from metarace import htlib
import csv
import os
import threading
from time import sleep

gi.require_version("GLib", "2.0")
from gi.repository import GLib

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

from metarace import jsonconfig
from metarace import tod
from metarace import eventdb
from metarace import riderdb
from metarace import strops
from metarace import report
from metarace import unt4
from metarace.telegraph import telegraph, _CONFIG_SCHEMA as _TG_SCHEMA
from metarace.export import mirror, _CONFIG_SCHEMA as _EXPORT_SCHEMA
from metarace.timy import timy, _CONFIG_SCHEMA as _TIMY_SCHEMA
from .sender import sender, _CONFIG_SCHEMA as _SENDER_SCHEMA
from .gemini import gemini
from . import uiutil
from . import scbwin
from . import eventdb

VERSION = '1.13.0'
LOGFILE = 'event.log'
LOGFILE_LEVEL = logging.DEBUG
CONFIGFILE = 'config.json'
TRACKMEET_ID = 'trackmeet-2.0'  # configuration versioning
EXPORTPATH = 'export'
MAXREP = 10000  # communique max number
SESSBREAKTHRESH = 0.075  # forced page break threshold
ANNOUNCE_LINELEN = 80  # length of lines on text-only DHI announcer

_log = logging.getLogger('trackmeet')
_log.setLevel(logging.DEBUG)
_CONFIG_SCHEMA = {
    'mtype': {
        'prompt': 'Meet Information',
        'control': 'section',
    },
}


def mkrace(meet, event, ui=True):
    """Return a race object of the correct type."""
    ret = None
    etype = event[u'type']
    ##if etype in [
    ##u'indiv tt', u'indiv pursuit', u'pursuit race', u'team pursuit',
    ##u'team pursuit race'
    ##]:
    ##ret = ittt.ittt(meet, event, ui)
    if etype in [u'points', u'madison', u'omnium']:
        ret = ps.ps(meet, event, ui)
    elif etype == u'classification':
        ret = classification.classification(meet, event, ui)
    ##elif etype in [u'flying 200', u'flying lap']:
    ##ret = f200.f200(meet, event, ui)
    ##elif etype in [u'hour']:
    ##ret = hour.hourrec(meet, event, ui)
    ##elif etype in [u'sprint round', u'sprint final']:
    ##ret = sprnd.sprnd(meet, event, ui)
    ##elif etype in [u'aggregate']:
    ##ret = aggregate.aggregate(meet, event, ui)
    else:
        ret = race.race(meet, event, ui)
    return ret


class trackmeet:
    """Track meet application class."""

    ## Meet Menu Callbacks
    def get_event(self, evno, ui=False):
        """Return an event object for the given event number."""
        # NOTE: returned event will need to be destroyed
        ret = None
        eh = self.edb[evno]
        if eh is not None:
            ret = mkrace(self, eh, ui)
        return ret

    def menu_meet_save_cb(self, menuitem, data=None):
        """Save current meet data and open event."""
        self.saveconfig()

    def menu_meet_info_cb(self, menuitem, data=None):
        """Display meet information on scoreboard."""
        self.gemini.clear()
        self.clock.clicked()

    def menu_meet_properties_cb(self, menuitem, data=None):
        """Edit meet properties."""
        _log.debug('TODO: Meet properties')
        return
        b = gtk.Builder()
        b.add_from_file(os.path.join(metarace.UI_PATH, 'trackmeet_props.ui'))
        dlg = b.get_object('properties')
        dlg.set_transient_for(self.window)

        # load meet meta
        tent = b.get_object('meet_title_entry')
        tent.set_text(self.titlestr)
        stent = b.get_object('meet_subtitle_entry')
        stent.set_text(self.subtitlestr)
        dent = b.get_object('meet_date_entry')
        dent.set_text(self.datestr)
        lent = b.get_object('meet_loc_entry')
        lent.set_text(self.locstr)
        cent = b.get_object('meet_comm_entry')
        cent.set_text(self.commstr)
        oent = b.get_object('meet_org_entry')
        oent.set_text(self.orgstr)

        # load data/result opts
        re = b.get_object('data_showevno')
        re.set_active(self.showevno)
        cm = b.get_object('data_clubmode')
        cm.set_active(self.clubmode)
        prov = b.get_object('data_provisional')
        prov.set_active(self.provisional)
        tln = b.get_object('tracklen_total')
        tln.set_value(self.tracklen_n)
        tld = b.get_object('tracklen_laps')
        tldl = b.get_object('tracklen_lap_label')
        tld.connect('value-changed', self.tracklen_laps_value_changed_cb, tldl)
        tld.set_value(self.tracklen_d)

        # scb/timing ports
        spe = b.get_object('scb_port_entry')
        if self.scbport is not None:
            spe.set_text(self.scbport)
        upe = b.get_object('uscb_port_entry')
        if self.anntopic is not None:
            upe.set_text(self.anntopic)
        spb = b.get_object('scb_port_dfl')
        spb.connect('clicked', self.set_default, spe, 'DEFAULT')
        mte = b.get_object('timing_main_entry')
        if self.main_port is not None:
            mte.set_text(self.main_port)
        mtb = b.get_object('timing_main_dfl')
        mtb.connect('clicked', self.set_default, mte, 'DEFAULT')

        # run dialog
        response = dlg.run()
        if response == 1:  # id 1 set in glade for "Apply"
            _log.debug('Updating meet properties')

            # update meet meta
            self.titlestr = tent.get_text().decode('utf-8', 'replace')
            self.subtitlestr = stent.get_text().decode('utf-8', 'replace')
            self.datestr = dent.get_text().decode('utf-8', 'replace')
            self.locstr = lent.get_text().decode('utf-8', 'replace')
            self.commstr = cent.get_text().decode('utf-8', 'replace')
            self.orgstr = oent.get_text().decode('utf-8', 'replace')
            self.set_title()

            self.clubmode = cm.get_active()
            self.showevno = re.get_active()
            self.provisional = prov.get_active()
            self.tracklen_n = tln.get_value_as_int()
            self.tracklen_d = tld.get_value_as_int()
            nport = spe.get_text().decode('utf-8', 'replace')
            if nport != self.scbport:
                # TODO: swap type handler if necessary
                self.scbport = nport
                self.scb.setport(nport)
            nport = upe.get_text().decode('utf-8', 'replace')
            if nport != self.anntopic:
                if self.anntopic is not None:
                    self.announce.unsubscribe('/'.join(
                        (self.anntopic, 'control', '#')))
                self.anntopic = None
                if nport:
                    self.anntopic = nport
                    self.announce.subscribe('/'.join(
                        (self.anntopic, 'control', '#')))
            nport = mte.get_text().decode('utf-8', 'replace')
            if nport != self.main_port:
                self.main_port = nport
                self.main_timer.setport(nport)
            _log.debug('Properties updated')
        else:
            _log.debug('Edit properties cancelled')
        dlg.destroy()

    def tracklen_laps_value_changed_cb(self, spin, lbl):
        """Laps changed in properties callback."""
        if int(spin.get_value()) > 1:
            lbl.set_text(' laps = ')
        else:
            lbl.set_text(' lap = ')

    def set_default(self, button, dest, val):
        """Update dest to default value val."""
        dest.set_text(val)

    def menu_meet_quit_cb(self, menuitem, data=None):
        """Quit the track meet application."""
        self.running = False
        self.window.destroy()

    def report_strings(self, rep):
        """Copy meet information into the supplied report."""
        rep.strings['title'] = self.titlestr
        rep.strings['host'] = self.host
        rep.strings['datestr'] = strops.promptstr('Date:', self.datestr)
        rep.strings['commstr'] = strops.promptstr('PCP:', self.pcp)
        rep.strings['orgstr'] = strops.promptstr('Organiser: ', self.orgstr)
        rep.strings['diststr'] = self.locstr

    ## Report print support
    def print_report(self,
                     sections=[],
                     subtitle='',
                     docstr='',
                     prov=False,
                     doprint=True,
                     exportfile=None):
        """Print the supplied sections in a standard report."""
        _log.info('Printing report %s %s', subtitle, docstr)

        rep = report.report()
        rep.provisional = prov
        self.report_strings(rep)
        rep.strings['subtitle'] = (self.subtitlestr + ' ' + subtitle).strip()
        rep.strings['docstr'] = docstr
        for sec in sections:
            rep.add_section(sec)

        # write out to files if exportfile set
        if exportfile:
            ofile = os.path.join(self.exportpath, exportfile + '.pdf')
            with metarace.savefile(ofile, mode='b') as f:
                rep.output_pdf(f)
            ofile = os.path.join(self.exportpath, exportfile + '.xls')
            with metarace.savefile(ofile, mode='b') as f:
                rep.output_xls(f)
            ofile = os.path.join(self.exportpath, exportfile + '.json')
            with metarace.savefile(ofile) as f:
                rep.output_json(f)
            lb = ''
            lt = []
            if self.mirrorpath:
                lb = os.path.join(self.linkbase, exportfile)
                lt = ['pdf', 'xls']
            ofile = os.path.join(self.exportpath, exportfile + '.html')
            with metarace.savefile(ofile) as f:
                rep.output_html(f, linkbase=lb, linktypes=lt)

        if not doprint:
            return False

        print_op = Gtk.PrintOperation.new()
        print_op.set_allow_async(True)
        print_op.set_print_settings(self.printprefs)
        print_op.set_default_page_setup(self.pageset)
        print_op.connect('begin_print', self.begin_print, rep)
        print_op.connect('draw_page', self.draw_print_page, rep)
        _log.debug('Calling into print_op.run()')
        res = print_op.run(Gtk.PrintOperationAction.PREVIEW, None)
        if res == Gtk.PrintOperationResult.APPLY:
            self.printprefs = print_op.get_print_settings()
            _log.debug('Updated print preferences')
        elif res == Gtk.PrintOperationResult.IN_PROGRESS:
            _log.debug('Print operation in progress')

        # may be called via idle_add
        return False

    def begin_print(self, operation, context, rep):
        """Set print pages and units."""
        rep.start_gtkprint(context.get_cairo_context())
        operation.set_use_full_page(True)
        operation.set_n_pages(rep.get_pages())
        operation.set_unit(Gtk.Unit.POINTS)

    def draw_print_page(self, operation, context, page_nr, rep):
        """Draw to the nominated page."""
        rep.set_context(context.get_cairo_context())
        rep.draw_page(page_nr)

    def find_communique(self, lookup):
        """Find or allocate a communique number."""
        ret = None
        cnt = 1
        noset = set()
        for c in self.commalloc:
            if c == lookup:  # previous allocation
                ret = self.commalloc[c]
                _log.debug('Found allocation: ' + ret + ' -> ' + lookup)
                break
            else:
                noset.add(self.commalloc[c])
        if ret is None:  # not yet allocated
            while True:
                ret = str(cnt)
                if ret not in noset:
                    self.commalloc[lookup] = ret  # write back
                    _log.debug('Add allocation: ' + ret + ' -> ' + lookup)
                    break
                else:
                    cnt += 1
                    if cnt > MAXREP:
                        _log.error('Gave up looking for communique no')
                        break  # safer
        return ret

    ## Event action callbacks
    def eventdb_cb(self, evlist, reptype=None):
        """Make a report containing start lists for the events listed."""
        # Note: selections via event listing override extended properties
        #       even if the selection does not really make sense, this
        #       allows for creation of reports manually crafted.
        secs = []
        reptypestr = reptype.title()
        lsess = None
        for eno in evlist:
            e = self.edb[eno]
            nsess = e['sess']
            if nsess != lsess and lsess is not None:
                secs.append(report.pagebreak(SESSBREAKTHRESH))
            lsess = nsess
            h = mkrace(self, e, False)
            h.loadconfig()
            if reptype == 'startlist':
                secs.extend(h.startlist_report())
            elif reptype == 'result':
                reptypestr = 'Results'
                # from event list only include the individual events
                secs.extend(h.result_report(recurse=False))
            elif reptype == 'program':
                reptypestr = 'Program of Events'
                secs.extend(h.startlist_report(True))  # startlist in program
            else:
                _log.error('Unknown report type in eventdb calback: ' +
                           repr(reptype))
            h.destroy()
            secs.append(report.pagebreak())
        if len(secs) > 0:
            reporthash = reptype + ', '.join(evlist)
            if False and self.communiques:  # prompt for communique no
                #commno = uiutil.communique_dialog(self.meet.window)

                #if commno is not None and len(commno) > 1:
                ##gtk.gdk.threads_enter()
                rvec = uiutil.edit_times_dlg(self.window, stxt='', ftxt='')
                ##gtk.gdk.threads_leave()
                if len(rvec) > 1 and rvec[0] == 1:
                    commno = self.find_communique(reporthash)
                    if rvec[1]:  # it's a revision
                        commno += rvec[1]
                    if commno is not None:
                        reptypestr = ('Communiqu\u00e9 ' + commno + ': ' +
                                      reptypestr)
                    if rvec[2]:
                        msgsec = report.bullet_text()
                        msgsec.subheading = 'Revision ' + repr(rvec[1])
                        msgsec.lines.append(['', rvec[2]])
                        ## signature
                        secs.append(msgsec)
            self.print_report(secs,
                              docstr=reptypestr,
                              exportfile='trackmeet_' + reptype)
        else:
            _log.info(reptype + ' callback: Nothing to report')
        return False

    ## Race menu callbacks.
    def menu_race_startlist_activate_cb(self, menuitem, data=None):
        """Generate a startlist."""
        sections = []
        if self.curevent is not None:
            sections.extend(self.curevent.startlist_report())
        self.print_report(sections)

    def menu_race_result_activate_cb(self, menuitem, data=None):
        """Generate a result."""
        sections = []
        if self.curevent is not None:
            sections.extend(self.curevent.result_report())
        self.print_report(sections, 'Result')

    def menu_race_make_activate_cb(self, menuitem, data=None):
        """Create and open a new race of the chosen type."""
        event = self.edb.add_empty()
        event['type'] = data
        # Backup an existing config
        oldconf = self.event_configfile(event['evid'])
        if os.path.isfile(oldconf):
            # There is already a config file for this event id
            bakfile = oldconf + '.old'
            _log.info('Existing config saved to %r', bakfile)
            os.rename(oldconf, bakfile)  ## TODO: replace with shutil
        self.open_event(event)
        self.menu_race_properties.activate()

    def menu_race_info_activate_cb(self, menuitem, data=None):
        """Show race information on scoreboard."""
        if self.curevent is not None:
            self.scbwin = None
            eh = self.curevent.event
            if self.showevno and eh['type'] not in ['break', 'session']:
                self.scbwin = scbwin.scbclock(self.scb, 'Event ' + eh['evid'],
                                              eh['pref'], eh['info'])
            else:
                self.scbwin = scbwin.scbclock(self.scb, eh['pref'], eh['info'])
            self.scbwin.reset()
            self.curevent.delayed_announce()

    def menu_race_properties_activate_cb(self, menuitem, data=None):
        """Edit properties of open race if possible."""
        if self.curevent is not None:
            self.curevent.do_properties()

    def menu_race_run_activate_cb(self, menuitem=None, data=None):
        """Open currently selected event."""
        eh = self.edb.getselected()
        if eh is not None:
            self.open_event(eh)

    def event_row_activated_cb(self, view, path, col, data=None):
        """Respond to activate signal on event row."""
        self.menu_race_run_activate_cb()

    def menu_race_next_activate_cb(self, menuitem, data=None):
        """Open the next event on the program."""
        if self.curevent is not None:
            nh = self.edb.getnextrow(self.curevent.event)
            if nh is not None:
                self.open_event(nh)
            else:
                _log.warning('No next event to open')
        else:
            eh = self.edb.getselected()
            if eh is not None:
                self.open_event(eh)
            else:
                _log.warning('No next event to open')

    def menu_race_prev_activate_cb(self, menuitem, data=None):
        """Open the previous event on the program."""
        if self.curevent is not None:
            ph = self.edb.getprevrow(self.curevent.event)
            if ph is not None:
                self.open_event(ph)
            else:
                _log.warning('No previous event to open')
        else:
            eh = self.edb.getselected()
            if eh is not None:
                self.open_event(eh)
            else:
                _log.warning('No previous event to open')

    def menu_race_close_activate_cb(self, menuitem, data=None):
        """Close currently open event."""
        self.close_event()

    def menu_race_abort_activate_cb(self, menuitem, data=None):
        """Close currently open event without saving."""
        if self.curevent is not None:
            self.curevent.readonly = True
        self.close_event()

    def open_event(self, eventhdl=None):
        """Open provided event handle."""
        if eventhdl is not None:
            self.close_event()
            newevent = mkrace(self, eventhdl)
            newevent.loadconfig()
            self.curevent = newevent
            self.race_box.add(self.curevent.frame)
            self.menu_race_info.set_sensitive(True)
            self.menu_race_close.set_sensitive(True)
            self.menu_race_abort.set_sensitive(True)
            self.menu_race_startlist.set_sensitive(True)
            self.menu_race_result.set_sensitive(True)
            starters = eventhdl['star']
            if starters is not None and starters != '':
                if 'auto' in starters:
                    spec = starters.lower().replace('auto', '').strip()
                    self.curevent.autospec += spec
                    _log.info('Transferred autospec ' + repr(spec) +
                              ' to event ' + self.curevent.evno)
                else:
                    self.addstarters(
                        self.curevent,
                        eventhdl,  # xfer starters
                        strops.reformat_biblist(starters))
                eventhdl['star'] = ''
            self.menu_race_properties.set_sensitive(True)
            self.curevent.show()

    def addstarters(self, race, event, startlist):
        """Add each of the riders in startlist to the opened race."""
        starters = startlist.split()
        for st in starters:
            # check for category
            rlist = self.rdb.biblistfromcat(st, race.series)
            if len(rlist) > 0:
                for est in rlist:
                    race.addrider(est)
            else:
                race.addrider(st)

    def autoplace_riders(self, race, autospec='', infocol=None, final=False):
        """Fetch a flat list of places from the autospec."""
        # TODO: Consider an alternative since this is only used by ps
        places = {}
        for egroup in autospec.split(';'):
            _log.debug('Autospec group: ' + repr(egroup))
            specvec = egroup.split(':')
            if len(specvec) == 2:
                evno = specvec[0].strip()
                if evno not in self.autorecurse:
                    self.autorecurse.add(evno)
                    placeset = strops.placeset(specvec[1])
                    e = self.edb[evno]
                    if e is not None:
                        h = mkrace(self, e, False)
                        h.loadconfig()
                        isFinal = h.standingstr() == 'Result'
                        _log.debug('Event %r status: %r, final=%r', evno,
                                   h.standingstr(), isFinal)
                        if not final or isFinal:
                            for ri in h.result_gen():
                                if isinstance(ri[1],
                                              int) and ri[1] in placeset:
                                    rank = ri[1]
                                    if rank not in places:
                                        places[rank] = []
                                    places[rank].append(ri[0])
                        h.destroy()
                    else:
                        _log.warning('Autospec event number not found: ' +
                                     repr(evno))
                    self.autorecurse.remove(evno)
                else:
                    _log.debug('Ignoring loop in auto placelist: ' +
                               repr(evno))
            else:
                _log.warning('Ignoring erroneous autospec group: ' +
                             repr(egroup))
        ret = ''
        for place in sorted(places):
            ret += ' ' + '-'.join(places[place])
        ## TODO: append to [] then join
        _log.debug('Place set: ' + ret)
        return ret

    def autostart_riders(self, race, autospec='', infocol=None, final=True):
        """Try to fetch the startlist from race result info."""
        # Dubious: infocol allows selection of seed info
        #          typical values:
        #                           1 -> timed event qualifiers
        #                           3 -> handicap
        # TODO: check default, maybe defer to None
        # TODO: IMPORTANT cache result gens for fast recall
        for egroup in autospec.split(';'):
            _log.debug('Autospec group: ' + repr(egroup))
            specvec = egroup.split(':')
            if len(specvec) == 2:
                evno = specvec[0].strip()
                if evno not in self.autorecurse:
                    self.autorecurse.add(evno)
                    placeset = strops.placeset(specvec[1])
                    e = self.edb[evno]
                    if e is not None:
                        evplacemap = {}
                        _log.debug('Loading places from event %r', evno)
                        ## load the place set map rank -> [[rider,seed],..]
                        h = mkrace(self, e, False)
                        h.loadconfig()
                        for ri in h.result_gen():
                            if isinstance(ri[1], int) and ri[1] in placeset:
                                rank = ri[1]
                                if rank not in evplacemap:
                                    evplacemap[rank] = []
                                seed = None
                                if infocol is not None and infocol < len(ri):
                                    seed = ri[infocol]
                                evplacemap[rank].append([ri[0], seed])
                                #_log.debug('Event %r add place=%r, rider=%r, info=%r',
                                #evno, rank, ri[0], seed)
                        h.destroy()
                        # maintain ordering of autospec
                        for p in placeset:
                            if p in evplacemap:
                                for ri in evplacemap[p]:
                                    #_log.debug(u'Adding rider: %r/%r', ri[0], ri[1])
                                    race.addrider(ri[0], ri[1])
                    else:
                        _log.warning('Autospec event number not found: ' +
                                     repr(evno))
                    self.autorecurse.remove(evno)
                else:
                    _log.debug('Ignoring loop in auto startlist: ' +
                               repr(evno))
            else:
                _log.warning('Ignoring erroneous autospec group: ' +
                             repr(egroup))

    def close_event(self):
        """Close the currently opened race."""
        if self.curevent is not None:
            self.menu_race_properties.set_sensitive(False)
            self.menu_race_info.set_sensitive(False)
            self.menu_race_close.set_sensitive(False)
            self.menu_race_abort.set_sensitive(False)
            self.menu_race_startlist.set_sensitive(False)
            self.menu_race_result.set_sensitive(False)
            # grab temporary handle to event to be closed
            delevent = self.curevent
            # invalidate curevent handle and then cleanup
            self.curevent = None
            delevent.hide()
            self.race_box.remove(delevent.frame)
            delevent.event['dirt'] = True  # mark event exportable
            delevent.destroy()

    def race_evno_change(self, old_no, new_no):
        """Handle a change in a race number."""
        if self.curevent is not None and self.curevent.evno == old_no:
            _log.warning('Ignoring change to open event: %r', old_no)
            return False
        newconf = self.event_configfile(new_no)
        if os.path.isfile(newconf):
            rnconf = newconf + '.old'
            _log.debug('Backup existing config to %r', rnconf)
            os.rename(newconf, rnconf)
        oldconf = self.event_configfile(old_no)
        if os.path.isfile(oldconf):
            _log.debug('Rename config %r to %r', oldconf, newconf)
            os.rename(oldconf, newconf)
        _log.debug('Event %r changed to %r', old_no, new_no)
        return True

    ## Data menu callbacks.
    def menu_data_import_activate_cb(self, menuitem, data=None):
        """Re-load event and rider info from disk."""
        if not uiutil.questiondlg(self.window,
                                  'Re-load event and rider data from disk?',
                                  'Note: The current event will be closed.'):
            _log.debug('Re-load events & riders aborted')
            return False

        cureventno = None
        if self.curevent is not None:
            cureventno = self.curevent.evno
            self.close_event()

        self.rdb.clear()
        self.edb.clear()
        self.edb.load('events.csv')
        self.rdb.load('riders.csv')
        self.reload_riders()

        if cureventno and cureventno in self.edb:
            self.open_event(self.edb[cureventno])
        else:
            _log.warning('Running event was removed from the event list')

    def menu_data_result_activate_cb(self, menuitem, data=None):
        """Export final result."""
        try:
            self.finalresult()  # TODO: Call in sep thread
        except Exception as e:
            _log.error('Error writing result: ' + str(e))
            raise

    def finalresult(self):
        provisional = self.provisional  # may be overridden below
        sections = []
        lastsess = None
        for e in self.edb:
            r = mkrace(self, e, False)
            if e['resu']:  # include in result
                nsess = e['sess']
                if nsess != lastsess:
                    sections.append(
                        report.pagebreak(SESSBREAKTHRESH))  # force break
                    _log.debug('Break between events: ' + repr(e['evid']) +
                               ' with ' + repr(lastsess) + ' != ' +
                               repr(nsess))
                lastsess = nsess
                if r.evtype in ['break', 'session']:
                    sec = report.section()
                    sec.heading = ' '.join([e['pref'], e['info']]).strip()
                    sec.subheading = '\t'.join(
                        [strops.lapstring(e['laps']), e['dist'],
                         e['prog']]).strip()
                    sections.append(sec)
                else:
                    r.loadconfig()
                    if r.onestart:  # in progress or done...
                        rep = r.result_report()
                    else:
                        rep = r.startlist_report()
                    if len(rep) > 0:
                        sections.extend(rep)
            r.destroy()

        filebase = 'result'
        self.print_report(sections,
                          'Results',
                          prov=provisional,
                          doprint=False,
                          exportfile=filebase.translate(strops.WEBFILE_UTRANS))

    def printprogram(self):
        r = report.report()
        subtitlestr = 'Program of Events'
        if self.subtitlestr:
            subtitlestr = self.subtitlestr + ' - ' + subtitlestr
        r.strings['title'] = self.titlestr
        r.strings['subtitle'] = subtitlestr
        r.strings['datestr'] = strops.promptstr('Date:', self.datestr)
        r.strings['commstr'] = strops.promptstr('Chief Commissaire:',
                                                self.commstr)
        r.strings['orgstr'] = strops.promptstr('Organiser: ', self.orgstr)
        r.strings['docstr'] = ''  # What should go here?
        r.strings['diststr'] = self.locstr

        r.set_provisional(self.provisional)

        cursess = None
        for e in self.edb:
            if e['prin']:  # include this event in program
                if e['sess']:  # add harder break for new session
                    if cursess and cursess != e['sess']:
                        r.add_section(report.pagebreak(SESSBREAKTHRESH))
                    cursess = e['sess']
                h = mkrace(self, e, False)
                h.loadconfig()
                s = h.startlist_report(True)
                for sec in s:
                    r.add_section(sec)
                h.destroy()

        filebase = 'program'
        ofile = os.path.join('export', filebase + '.pdf')
        with metarace.savefile(ofile) as f:
            r.output_pdf(f, docover=True)
            _log.info('Exported pdf program to %r', ofile)
        ofile = os.path.join('export', filebase + '.html')
        with metarace.savefile(ofile) as f:
            r.output_html(f)
            _log.info('Exported html program to %r', ofile)
        ofile = os.path.join('export', filebase + '.xls')
        with metarace.savefile(ofile) as f:
            r.output_xls(f)
            _log.info('Exported xls program to %r', ofile)
        ofile = os.path.join('export', filebase + '.json')
        with metarace.savefile(ofile) as f:
            r.output_json(f)
            _log.info('Exported json program to %r', ofile)

    def menu_data_program_activate_cb(self, menuitem, data=None):
        """Export race program."""
        try:
            self.printprogram()  # TODO: call from sep thread
        except Exception as e:
            _log.error('Error writing report: ' + str(e))
            raise

    def menu_data_update_activate_cb(self, menuitem, data=None):
        """Update meet, session, event and riders in external database."""
        try:
            _log.info('Exporting data:')
            self.updateindex()  # TODO: push into sep thread
        except Exception as e:
            _log.error('Error exporting event data: ' + str(e))
            raise

    def updatenexprev(self):
        self.nextlinks = {}
        self.prevlinks = {}
        evlinks = {}
        evidx = []
        for eh in self.edb:
            if eh['inde'] or eh['resu']:  # include in index?
                evno = eh['evid']
                referno = None
                if eh['type'] not in ['break', 'session']:
                    referno = evno
                if eh['refe']:  # overwrite ref no, even on specials
                    referno = eh['refe']
                linkfile = None
                if referno:
                    if referno not in evlinks:
                        evidx.append(referno)
                        evlinks[referno] = 'event_' + str(referno).translate(
                            strops.WEBFILE_UTRANS)
        prevno = None
        for evno in evidx:
            if prevno is not None:
                self.nextlinks[prevno] = evlinks[evno]
                self.prevlinks[evno] = evlinks[prevno]
            prevno = evno

    def updateindex(self):
        self.reload_riders()  # re-read rider list
        self.updatenexprev()  # re-compute next/prev link struct
        # check for printed program link
        # check for final result link
        # check for timing log link
        # build index of events report
        if self.mirrorpath:
            orep = report.report()
            orep.strings['title'] = self.titlestr
            orep.strings['subtitle'] = self.subtitlestr
            orep.strings['datestr'] = strops.promptstr('Date:', self.datestr)
            orep.strings['commstr'] = strops.promptstr('Chief Commissaire:',
                                                       self.commstr)
            orep.strings['orgstr'] = strops.promptstr('Organiser: ',
                                                      self.orgstr)
            orep.strings['diststr'] = self.locstr
            orep.set_provisional(self.provisional)  # ! TODO
            orep.shortname = self.titlestr
            orep.indexlink = '/'
            if self.provisional:
                orep.reportstatus = 'provisional'
            else:
                orep.reportstatus = 'final'

            pfilebase = 'program'
            pfile = os.path.join('export', pfilebase + '.pdf')
            rfilebase = 'result'
            rfile = os.path.join('export', rfilebase + '.pdf')

            lt = []
            lb = None
            if os.path.exists(rfile):
                lt = ['pdf', 'xls']
                lb = os.path.join(self.linkbase, rfilebase)
            elif os.path.exists(pfile):
                lt = ['pdf', 'xls']
                lb = os.path.join(self.linkbase, pfilebase)

            sec = report.event_index('eventindex')
            sec.heading = 'Index of Events'
            #sec.subheading = Date?
            for eh in self.edb:
                if eh['inde']:  # include in index?
                    evno = eh['evid']
                    if eh['type'] in ['break', 'session']:
                        evno = None
                    referno = evno
                    if eh['refe']:  # overwrite ref no, even on specials
                        referno = eh['refe']
                    linkfile = None
                    if referno:
                        linkfile = 'event_' + str(referno).translate(
                            strops.WEBFILE_UTRANS)
                    descr = ' '.join([eh['pref'], eh['info']]).strip()
                    extra = None  # STATUS INFO -> progress?
                    if eh['evov'] is not None and eh['evov'] != '':
                        evno = eh['evov'].strip()
                    sec.lines.append([evno, None, descr, extra, linkfile])
            orep.add_section(sec)
            basename = 'index'
            ofile = os.path.join(self.exportpath, basename + '.html')
            with metarace.savefile(ofile) as f:
                orep.output_html(f, linkbase=lb, linktypes=lt)
            jbase = basename + '.json'
            ofile = os.path.join(self.exportpath, jbase)
            with metarace.savefile(ofile) as f:
                orep.output_json(f)
            GLib.idle_add(self.mirror_start)

    def mirror_completion(self, status, updates):
        """Send notifies for any changed files sent after export."""
        # NOTE: called in the mirror thread
        _log.debug('Mirror status: %r', status)
        if status == 0:
            pass
        else:
            _log.error('Mirror failed')
        return False

    def mirror_start(self, dirty=None):
        """Create a new mirror thread unless in progress."""
        if self.mirrorpath and self.mirror is None:
            self.mirror = export.mirror(callback=self.mirror_completion,
                                        callbackdata=dirty,
                                        localpath=os.path.join(
                                            self.exportpath, ''),
                                        remotepath=self.mirrorpath,
                                        mirrorcmd=self.mirrorcmd)
            self.mirror.start()
        return False  # for idle_add

    def menu_data_export_activate_cb(self, menuitem, data=None):
        """Export race data."""
        if not self.exportlock.acquire(False):
            _log.info('Export already in progress')
            return None  # allow only one entry
        if self.exporter is not None:
            _log.warning('Export in progress, re-run required')
            return False
        try:
            self.exporter = threading.Thread(target=self.__run_data_export)
            self.exporter.start()
            _log.debug('Created export worker %r: ', self.exporter)
        finally:
            self.exportlock.release()

    def __run_data_export(self):
        try:
            _log.debug('Exporting race info')
            self.updatenexprev()  # re-compute next/prev link struct

            # determine 'dirty' events 	## TODO !!
            dmap = {}
            dord = []
            for e in self.edb:  # note - this is the only traversal
                series = e['seri']
                #if series not in rmap:
                #rmap[series] = {}
                evno = e['evid']
                etype = e['type']
                prefix = e['pref']
                info = e['info']
                export = e['resu']
                key = evno  # no need to concat series, evno is unique
                dirty = e['dirt']
                if not dirty:  # check for any dependencies
                    for dev in e['depe'].split():
                        if dev in dmap:
                            dirty = True
                            break
                if dirty:
                    dord.append(key)  # maintains ordering
                    dmap[key] = [e, evno, etype, series, prefix, info, export]
            _log.debug('Marked ' + str(len(dord)) + ' events dirty')

            dirty = {}
            for k in dmap:  # only output dirty events
                # turn key into read-only event handle
                e = dmap[k][0]
                evno = dmap[k][1]
                etype = dmap[k][2]
                series = dmap[k][3]
                evstr = (dmap[k][4] + ' ' + dmap[k][5]).strip()
                doexport = dmap[k][6]
                e['dirt'] = False
                r = mkrace(self, e, False)
                r.loadconfig()

                # starters
                stcount = 0
                # this may not be required anymore - check
                startrep = r.startlist_report()  # trigger rider model reorder

                if self.mirrorpath and doexport:
                    orep = report.report()
                    orep.strings['title'] = self.titlestr
                    orep.strings['subtitle'] = evstr
                    #orep.strings[u'datestr'] = strops.promptstr(u'Date:',
                    #self.datestr)
                    # orep.strings[u'diststr'] = self.locstr
                    orep.strings['docstr'] = evstr
                    if etype in ['classification']:
                        orep.strings['docstr'] += ' Classification'
                    orep.set_provisional(self.provisional)  # ! TODO
                    if self.provisional:
                        orep.reportstatus = 'provisional'
                    else:
                        orep.reportstatus = 'final'

                    # in page links
                    orep.shortname = evstr
                    orep.indexlink = './'  # url to program of events
                    if evno in self.prevlinks:
                        orep.prevlink = self.prevlinks[evno]
                    if evno in self.nextlinks:
                        orep.nextlink = self.nextlinks[evno]

                    # update files and trigger mirror
                    if r.onestart:  # output result
                        outsec = r.result_report()
                        for sec in outsec:
                            orep.add_section(sec)
                    else:  # startlist
                        outsec = r.startlist_report('startlist')
                        for sec in outsec:
                            orep.add_section(sec)
                    basename = 'event_' + str(evno).translate(
                        strops.WEBFILE_UTRANS)
                    ofile = os.path.join(self.exportpath, basename + '.html')
                    with metarace.savefile(ofile) as f:
                        orep.output_html(f)
                    jbase = basename + '.json'
                    ofile = os.path.join(self.exportpath, jbase)
                    with metarace.savefile(ofile) as f:
                        orep.output_json(f)
                r.destroy()
            GLib.idle_add(self.mirror_start)
            _log.debug('Race info export')
        except Exception as e:
            _log.error('Error exporting results: %s', e)

    ## SCB menu callbacks
    def menu_scb_enable_toggled_cb(self, button, data=None):
        """Update scoreboard enable setting."""
        if button.get_active():
            self.scb.set_ignore(False)
            self.scb.setport(self.scbport)
            if self.scbwin is not None:
                self.scbwin.reset()
        else:
            self.scb.set_ignore(True)

    def menu_scb_clock_cb(self, menuitem, data=None):
        """Select timer scoreboard overlay."""
        self.gemini.clear()
        self.scbwin = None  # stop sending any new updates
        self.scb.clrall()  # force clear of current text page
        self.scb.sendmsg(unt4.OVERLAY_CLOCK)
        _log.debug('Show facility clock')

    def menu_scb_blank_cb(self, menuitem, data=None):
        """Select blank scoreboard overlay."""
        self.gemini.clear()
        self.scbwin = None
        self.scb.clrall()
        self.txt_announce(unt4.GENERAL_CLEARING)
        _log.debug('Blank scoreboard')

    def menu_scb_test_cb(self, menuitem, data=None):
        """Select test scoreboard overlay."""
        self.scbwin = None
        self.scbwin = scbwin.scbtest(self.scb)
        self.scbwin.reset()
        _log.debug('Scoreboard testpage')

    def menu_scb_connect_activate_cb(self, menuitem, data=None):
        """Force a reconnect to scoreboards."""
        self.scb.setport(self.scbport)
        self.announce.reconnect()
        _log.debug('Re-connect scoreboard')
        if self.gemport != '':
            self.gemini.setport(self.gemport)

    def entry_set_now(self, button, entry=None):
        """Enter the current time in the provided entry."""
        entry.set_text(tod.now().timestr())
        entry.activate()

    def menu_timing_recalc(self, entry, ste, fte, nte):
        """Update the net time entry for the supplied start and finish."""
        st = tod.mktod(ste.get_text().decode('utf-8', 'replace'))
        ft = tod.mktod(fte.get_text().decode('utf-8', 'replace'))
        if st is not None and ft is not None:
            ste.set_text(st.timestr())
            fte.set_text(ft.timestr())
            nte.set_text((ft - st).timestr())

    def menu_timing_clear_activate_cb(self, menuitem, data=None):
        """Clear memory in attached timing devices."""
        self.main_timer.clrmem()
        _log.info('Clear timer memory')

    def menu_timing_dump_activate_cb(self, menuitem, data=None):
        """Request memory dump from attached timy."""
        self.main_timer.dumpall()
        _log.info('Dump timer memory')

    def menu_timing_reconnect_activate_cb(self, menuitem, data=None):
        """Reconnect timer and initialise."""
        self.main_timer.setport(self.main_port)
        if self.main_port:
            self.main_timer.sane()
        _log.info('Re-connect and initialise timer')

    ## Help menu callbacks
    def menu_help_about_cb(self, menuitem, data=None):
        """Display metarace about dialog."""
        uiutil.about_dlg(self.window, VERSION)

    ## Menu button callbacks
    def menu_clock_clicked_cb(self, button, data=None):
        """Handle click on menubar clock."""
        (line1, line2,
         line3) = strops.titlesplit(self.titlestr + ' ' + self.subtitlestr,
                                    self.scb.linelen)
        self.scbwin = scbwin.scbclock(self.scb,
                                      line1,
                                      line2,
                                      line3,
                                      locstr=self.locstr)
        self.scbwin.reset()

    ## Directory utilities
    def event_configfile(self, evno):
        """Return a config filename for the given event no."""
        return 'event_{}.json'.format(str(evno))

    ## Timer callbacks
    def menu_clock_timeout(self):
        """Update time of day on clock button."""

        if not self.running:
            return False
        else:
            nt = tod.now().meridiem()
            if self.scb.connected():
                self.rfustat.update('ok', nt)
            else:
                self.rfustat.update('idle', nt)

            # check for completion in the export workers
            if self.mirror is not None:
                if not self.mirror.is_alive():  # replaces join() non-blocking
                    self.mirror = None
            if self.exporter is not None:
                if not self.exporter.is_alive(
                ):  # replaces join() non-blocking
                    _log.debug('Deleting complete export: %r', self.exporter)
                    self.exporter = None
                else:
                    _log.info('Incomplete export: %r', self.exporter)
        return True

    def timeout(self):
        """Update internal state and call into race timeout."""
        if not self.running:
            return False
        try:
            if self.curevent is not None:
                self.curevent.timeout()
            if self.scbwin is not None:
                self.scbwin.update()
        except Exception as e:
            _log.error('%s in timeout: %s', e.__class__.__name__, e)
        return True

    ## Timy utility methods.
    def timer_reprint(self, event='', trace=[]):
        self.main_timer.printer(True)  # turn on printer
        self.main_timer.printimp(False)  # suppress intermeds
        self.main_timer.printline('')
        self.main_timer.printline('')
        self.main_timer.printline(self.titlestr)
        self.main_timer.printline(self.subtitlestr)
        self.main_timer.printline('')
        if event:
            self.main_timer.printline(event)
            self.main_timer.printline('')
        for l in trace:
            self.main_timer.printline(l)
        self.main_timer.printline('')
        self.main_timer.printline('')
        self.main_timer.printer(False)

    def delayimp(self, dtime):
        """Set the impulse delay time."""
        self.main_timer.delaytime(dtime)

    def timer_log_event(self, ev=None):
        self.main_timer.printline(self.racenamecat(ev, slen=20, halign='l'))

    def timer_log_straight(self, bib, msg, tod, prec=4):
        """Print a tod log entry on the Timy receipt."""
        lstr = '{0:3} {1: >5}:{2}'.format(bib[0:3], msg[0:5],
                                          tod.timestr(prec))
        self.main_timer.printline(lstr)

    def timer_log_msg(self, bib, msg):
        """Print the given msg entry on the Timy receipt."""
        lstr = '{0:3} {1}'.format(bib[0:3], str(msg)[0:20])
        self.main_timer.printline(lstr)

    def event_string(self, evno):
        """Switch to suppress event no in delayed announce screens."""
        ret = ''
        if self.showevno:
            ret = 'Event ' + str(evno)
        else:
            ret = ' '.join([self.titlestr, self.subtitlestr]).strip()
        return ret

    def infoline(self, event):
        """Format event information for display on event info label."""
        evstr = event['pref'] + ' ' + event['info']
        if len(evstr) > 44:
            evstr = evstr[0:47] + '\u2026'
        etype = event['type']
        return ('Event {}: {} [{}]'.format(event['evid'], evstr, etype))

    def racenamecat(self, event, slen=None, tail='', halign='c'):
        """Concatentate race info for display on scoreboard header line."""
        if slen is None:
            slen = self.scb.linelen
        evno = ''
        srcev = event['evid']
        if self.showevno and event['type'] not in ['break', 'session']:
            evno = 'Ev ' + srcev
        info = event['info']
        prefix = event['pref']
        ret = ' '.join([evno, prefix, info, tail]).strip()
        if len(ret) > slen + 1:
            ret = ' '.join([evno, info, tail]).strip()
            if len(ret) > slen + 1:
                ret = ' '.join([evno, tail]).strip()
        return strops.truncpad(ret, slen, align=halign)

    def racename(self, event):
        """Return a full event identifier string."""
        evno = ''
        if self.showevno and event['type'] not in ['break', 'session']:
            evno = 'Event ' + event['evid']
        info = event['info']
        prefix = event['pref']
        return ' '.join([evno, prefix, info]).strip()

    ## Announcer methods
    def cmd_announce(self, command, msg):
        """Announce the supplied message to the command topic."""
        if self.anntopic:
            topic = '/'.join((self.anntopic, command))
            self.announce.publish(msg, topic)

    def txt_announce(self, umsg):
        """Announce the unt4 message to the text-only DHI announcer."""
        if self.anntopic:
            topic = '/'.join((self.anntopic, 'text'))
            self.announce.publish(umsg.pack(), topic)

    def txt_clear(self):
        """Clear the text announcer."""
        self.txt_announce(unt4.GENERAL_CLEARING)

    def txt_default(self):
        self.txt_announce(
            unt4.unt4(xx=1,
                      yy=0,
                      erl=True,
                      text=strops.truncpad(
                          ' '.join([
                              self.titlestr, self.subtitlestr, self.datestr
                          ]).strip(), ANNOUNCE_LINELEN - 2, 'c')))

    def txt_title(self, titlestr=''):
        self.txt_announce(
            unt4.unt4(xx=1,
                      yy=0,
                      erl=True,
                      text=strops.truncpad(titlestr.strip(),
                                           ANNOUNCE_LINELEN - 2, 'c')))

    def txt_line(self, line, char='_'):
        self.txt_announce(
            unt4.unt4(xx=0, yy=line, text=char * ANNOUNCE_LINELEN))

    def txt_setline(self, line, msg):
        self.txt_announce(unt4.unt4(xx=0, yy=line, erl=True, text=msg))

    def txt_postxt(self, line, oft, msg):
        self.txt_announce(unt4.unt4(xx=oft, yy=line, text=msg))

    ## Window methods
    def set_title(self, extra=''):
        """Update window title from meet properties."""
        self.window.set_title(
            'trackmeet: ' +
            ' '.join([self.titlestr, self.subtitlestr]).strip())
        self.txt_default()

    def meet_destroy_cb(self, window, msg=''):
        """Handle destroy signal and exit application."""
        rootlogger = logging.getLogger()
        rootlogger.removeHandler(self.sh)
        rootlogger.removeHandler(self.lh)
        self.window.hide()
        GLib.idle_add(self.meet_destroy_handler)

    def meet_destroy_handler(self):
        lastevent = None
        if self.curevent is not None:
            lastevent = self.curevent.evno
            self.close_event()
        if self.started:
            self.saveconfig(lastevent)
            self.shutdown()
        rootlogger = logging.getLogger()
        if self.loghandler is not None:
            rootlogger.removeHandler(self.loghandler)
        self.running = False
        Gtk.main_quit()
        return False

    def key_event(self, widget, event):
        """Collect key events on main window and send to race."""
        if event.type == Gdk.EventType.KEY_PRESS:
            key = Gdk.keyval_name(event.keyval) or 'None'
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                if key in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']:
                    t = tod.now(chan='MAN', refid=str(key))
                    self.__timercb(t)
                    return True
            if self.curevent is not None:
                return self.curevent.key_event(widget, event)
        return False

    def shutdown(self, msg=''):
        """Cleanly shutdown threads and close application."""
        self.started = False
        self.gemini.exit(msg)
        self.announce.exit(msg)
        self.scb.exit(msg)
        self.main_timer.exit(msg)
        _log.info('Waiting for workers to exit')
        if self.exporter is not None:
            _log.debug('Result compiler')
            self.exporter.join()
            self.exporter = None
        if self.mirror is not None:
            _log.debug('Result export')
            self.mirror.join()
            self.mirror = None
        _log.debug('Gemini scoreboard')
        self.gemini.join()
        _log.debug('DHI scoreboard')
        self.scb.join()
        _log.debug('Telegraph/announce')
        self.announce.join()
        _log.debug('Main timer')
        self.main_timer.join()

    def __timercb(self, evt, data=None):
        if self.curevent is not None:
            GLib.idle_add(self.curevent.timercb,
                          evt,
                          priority=GLib.PRIORITY_HIGH)

    def __controlcb(self, topic=None, message=None):
        _log.debug('Unsupported control %r: %r', topic, message)

    def start(self):
        """Start the timer and scoreboard threads."""
        if not self.started:
            _log.debug('Meet startup')
            self.announce.start()
            self.scb.start()
            self.main_timer.setcb(self.__timercb)
            self.main_timer.start()
            self.gemini.start()
            self.started = True

    # Track meet functions
    def delayed_export(self):
        """Queue an export on idle add."""
        self.exportpending = True
        GLib.idle_add(self.exportcb)

    def save_curevent(self):
        """Backup and save current event."""
        conf = self.event_configfile(self.curevent.event['evid'])
        backup = conf + '.1'
        try:  # minimal effort backup (Posix only)
            if os.path.isfile(backup):
                os.remove(backup)
            if os.path.isfile(conf):
                _log.debug('Backing up %r to %r', conf, backup)
                os.link(conf, backup)
        except Exception as e:
            _log.debug('Backup of %r to %r failed: %s', conf, backup, e)
        self.curevent.saveconfig()
        self.curevent.event['dirt'] = True

    def exportcb(self):
        """Save current event and update race info in external db."""
        if not self.exportpending:
            return False  # probably doubled up
        self.exportpending = False
        if self.curevent is not None and self.curevent.winopen:
            self.save_curevent()
        self.menu_data_export_activate_cb(None)
        return False  # for idle add

    def saveconfig(self, lastevent=None):
        """Save current meet data to disk."""
        cw = jsonconfig.config()
        cw.add_section('trackmeet')
        cw.set('trackmeet', 'id', TRACKMEET_ID)
        if self.curevent is not None and self.curevent.winopen:
            self.save_curevent()
            cw.set('trackmeet', 'curevent', self.curevent.evno)
        elif lastevent is not None:
            cw.set('trackmeet', 'curevent', lastevent)
        cw.set('trackmeet', 'timerprint', self.timerprint)
        cw.set('trackmeet', 'maintimer', self.main_port)
        cw.set('trackmeet', 'gemini', self.gemport)
        cw.set('trackmeet', 'racetimer', 'main')
        cw.set('trackmeet', 'scbport', self.scbport)
        cw.set('trackmeet', 'anntopic', self.anntopic)
        cw.set('trackmeet', 'title', self.titlestr)
        cw.set('trackmeet', 'subtitle', self.subtitlestr)
        cw.set('trackmeet', 'date', self.datestr)
        cw.set('trackmeet', 'location', self.locstr)
        cw.set('trackmeet', 'organiser', self.orgstr)
        cw.set('trackmeet', 'commissaire', self.commstr)
        cw.set('trackmeet', 'mirrorpath', self.mirrorpath)
        cw.set('trackmeet', 'mirrorcmd', self.mirrorcmd)
        cw.set('trackmeet', 'linkbase', self.linkbase)
        cw.set('trackmeet', 'clubmode', self.clubmode)
        cw.set('trackmeet', 'showevno', self.showevno)
        cw.set('trackmeet', 'provisional', self.provisional)
        cw.set('trackmeet', 'communiques', self.communiques)
        cw.set('trackmeet', 'commalloc', self.commalloc)  # map
        cw.set('trackmeet', 'tracklen_n', str(self.tracklen_n))  # poss val?
        cw.set('trackmeet', 'tracklen_d', str(self.tracklen_d))
        cw.set('trackmeet', 'docindex', str(self.docindex))
        with metarace.savefile(CONFIGFILE) as f:
            cw.write(f)
        self.rdb.save('riders.csv')
        self.edb.save('events.csv')
        _log.info('Meet configuration saved')

    def reload_riders(self):
        # make a prelim mapped rider struct
        _log.debug('TODO: load mapped riders?')
        #self.ridermap = {}
        #for s in self.rdb.listseries():
            #self.ridermap[s] = self.rdb.mkridermap(s)

    def loadconfig(self):
        """Load meet config from disk."""
        cr = jsonconfig.config({
            'trackmeet': {
                'maintimer': '',
                'timerprint': False,
                'racetimer': 'main',
                'scbport': '',
                'anntopic': None,
                'showevno': True,
                'resultnos': True,
                'clubmode': True,
                'tracklen_n': 250,
                'tracklen_d': 1,
                'docindex': '0',
                'gemini': '',
                'dbhost': '',
                'title': '',
                'subtitle': '',
                'date': '',
                'location': '',
                'organiser': '',
                'commissaire': '',
                'curevent': '',
                'mirrorcmd': '',
                'mirrorpath': '',
                'linkbase': '.',
                'provisional': False,
                'communiques': False,
                'commalloc': {},
                'id': ''
            }
        })
        cr.add_section('trackmeet')
        cr.merge(metarace.sysconf, 'trackmeet')
        _log.debug('Load system meet defaults')

        # re-set main log file
        _log.debug('Adding meet logfile handler %r', LOGFILE)
        rootlogger = logging.getLogger()
        if self.loghandler is not None:
            rootlogger.removeHandler(self.loghandler)
            self.loghandler.close()
            self.loghandler = None
        self.loghandler = logging.FileHandler(LOGFILE)
        self.loghandler.setLevel(LOGFILE_LEVEL)
        self.loghandler.setFormatter(logging.Formatter(metarace.LOGFILEFORMAT))
        rootlogger.addHandler(self.loghandler)

        # check for config file
        try:
            with open(CONFIGFILE, 'rb') as f:
                cr.read(f)
            _log.debug('Read meet config from %r', CONFIGFILE)
        except Exception as e:
            _log.error('Unable to read meet config: %s', e)

        # set main timer port (only main timer now)
        nport = cr.get('trackmeet', 'maintimer')
        if nport != self.main_port:
            self.main_port = nport
            self.main_timer.setport(nport)
            self.main_timer.sane()

        # add gemini board if defined
        self.gemport = cr.get('trackmeet', 'gemini')
        if self.gemport != '':
            self.gemini.setport(self.gemport)

        # flag timer print in time-trial mode
        self.timerprint = strops.confopt_bool(cr.get('trackmeet',
                                                     'timerprint'))

        # reset announcer topic
        self.anntopic = cr.get('trackmeet', 'anntopic')
        if self.anntopic:
            self.announce.subscribe('/'.join((self.anntopic, 'control', '#')))

        # connect DHI scoreboard
        nport = cr.get('trackmeet', 'scbport')
        if self.scbport != nport:
            self.scbport = nport
            self.scb.setport(nport)

        # set meet meta infos, and then copy into text entries
        self.titlestr = cr.get('trackmeet', 'title')
        self.subtitlestr = cr.get('trackmeet', 'subtitle')
        self.datestr = cr.get('trackmeet', 'date')
        self.locstr = cr.get('trackmeet', 'location')
        self.orgstr = cr.get('trackmeet', 'organiser')
        self.commstr = cr.get('trackmeet', 'commissaire')
        self.mirrorpath = cr.get('trackmeet', 'mirrorpath')
        self.mirrorcmd = cr.get('trackmeet', 'mirrorcmd')
        self.linkbase = cr.get('trackmeet', 'linkbase')
        self.set_title()

        # result options (bool)
        self.clubmode = strops.confopt_bool(cr.get('trackmeet', 'clubmode'))
        self.showevno = strops.confopt_bool(cr.get('trackmeet', 'showevno'))
        self.provisional = strops.confopt_bool(
            cr.get('trackmeet', 'provisional'))
        self.communiques = strops.confopt_bool(
            cr.get('trackmeet', 'communiques'))
        # communique allocations -> fixed once only
        self.commalloc = cr.get('trackmeet', 'commalloc')

        # track length
        n = strops.confopt_posint(cr.get('trackmeet', 'tracklen_n'), 0)
        d = strops.confopt_posint(cr.get('trackmeet', 'tracklen_d'), 0)
        setlen = False
        if n > 0 and n < 5500 and d > 0 and d < 10:  # sanity check
            self.tracklen_n = n
            self.tracklen_d = d
            setlen = True
            _log.debug('Track length updated to %r/%r', n, d)
        if not setlen:
            _log.warning('Ignoring invalid track length %r/%r default used', n,
                         d)

        # document id
        self.docindex = strops.confopt_posint(cr.get('trackmeet', 'docindex'),
                                              0)
        self.rdb.clear()
        self.edb.clear()
        self.edb.load('events.csv')
        self.rdb.load('riders.csv')
        self.reload_riders()

        cureventno = cr.get('trackmeet', 'curevent')
        if cureventno and cureventno in self.edb:
            self.open_event(self.edb[cureventno])

        # make sure export path exists
        if not os.path.exists(self.exportpath):
            os.mkdir(self.exportpath)
            _log.info('Created export path: %r', self.exportpath)

        # check and warn of config mismatch
        cid = cr.get('trackmeet', 'id')
        if cid != TRACKMEET_ID:
            _log.warning('Meet config mismatch: %r != %r', cid, TRACKMEET_ID)

    def newgetrider(self, bib, series=''):
        ret = None
        if series in self.ridermap and bib in self.ridermap[series]:
            ret = self.ridermap[series][bib]
        return ret

    def rider_edit(self, bib, series='', col=-1, value=''):
        dbr = self.rdb.getrider(bib, series)
        if dbr is None:
            dbr = self.rdb.addempty(bib, series)
        if col == riderdb.COL_FIRST:
            self.rdb.editrider(ref=dbr, first=value)
        elif col == riderdb.COL_LAST:
            self.rdb.editrider(ref=dbr, last=value)
        elif col == riderdb.COL_ORG:
            self.rdb.editrider(ref=dbr, org=value)
        else:
            _log.debug('Attempt to edit unsupported rider column: %r', col)
        self.reload_riders()

    def get_clubmode(self):
        return self.clubmode

    def get_distance(self, count=None, units='metres'):
        """Convert race distance units to metres."""
        ret = None
        if count is not None:
            try:
                if units in ['metres', 'meters']:
                    ret = int(count)
                elif units == 'laps':
                    ret = self.tracklen_n * int(count)
                    if self.tracklen_d != 1 and self.tracklen_d > 0:
                        ret //= self.tracklen_d
                _log.debug('get_distance: %r %r -> %dm', count, units, ret)
            except (ValueError, TypeError, ArithmeticError) as v:
                _log.warning('Error computing race distance: %s', v)
        return ret

    def __init__(self, lockfile=None):
        """Meet constructor."""
        self.loghandler = None  # set in loadconfig to meet dir
        self.exportpath = EXPORTPATH
        self.meetlock = lockfile
        self.titlestr = ''
        self.subtitlestr = ''
        self.datestr = ''
        self.locstr = ''
        self.orgstr = ''
        self.commstr = ''
        self.clubmode = True
        self.showevno = True
        self.provisional = False
        self.communiques = False
        self.nextlinks = {}
        self.prevlinks = {}
        self.commalloc = {}
        self.timerport = None
        self.tracklen_n = 250  # numerator
        self.tracklen_d = 1  # denominator
        self.docindex = 0  # used for session number
        self.exportpending = False
        self.mirrorpath = ''  # default mirror path
        self.mirrorcmd = ''  # default mirror command
        self.linkbase = '.'

        # printer preferences
        paper = Gtk.PaperSize.new_custom('metarace-full', 'A4 for reports',
                                         595, 842, Gtk.Unit.POINTS)
        self.printprefs = Gtk.PrintSettings.new()
        self.pageset = Gtk.PageSetup.new()
        self.pageset.set_orientation(Gtk.PageOrientation.PORTRAIT)
        self.pageset.set_paper_size(paper)
        self.pageset.set_top_margin(0, Gtk.Unit.POINTS)
        self.pageset.set_bottom_margin(0, Gtk.Unit.POINTS)
        self.pageset.set_left_margin(0, Gtk.Unit.POINTS)
        self.pageset.set_right_margin(0, Gtk.Unit.POINTS)

        # hardware connections
        _log.debug('Adding hardware connections')
        self.scb = sender()
        self.announce = telegraph()
        self.announce.setcb(self.__controlcb)
        self.scbport = ''
        self.anntopic = None
        self.timerprint = False  # enable timer printer?
        self.main_timer = timy()
        self.main_port = ''
        self.gemini = gemini()
        self.gemport = ''
        self.mirror = None  # file mirror thread
        self.exporter = None  # export worker thread
        self.exportlock = threading.Lock()  # one only exporter

        b = uiutil.builder('trackmeet.ui')
        self.window = b.get_object('meet')
        self.window.connect('key-press-event', self.key_event)
        self.rfustat = uiutil.statButton()
        self.rfustat.set_sensitive(True)
        b.get_object('menu_clock').add(self.rfustat)
        self.rfustat.update('idle', '--') 

        self.status = b.get_object('status')
        self.log_buffer = b.get_object('log_buffer')
        self.log_view = b.get_object('log_view')
        #self.log_view.modify_font(uiutil.LOGVIEWFONT)
        self.log_scroll = b.get_object('log_box').get_vadjustment()
        self.context = self.status.get_context_id('metarace meet')
        self.menu_race_info = b.get_object('menu_race_info')
        self.menu_race_properties = b.get_object('menu_race_properties')
        self.menu_race_close = b.get_object('menu_race_close')
        self.menu_race_abort = b.get_object('menu_race_abort')
        self.menu_race_startlist = b.get_object('menu_race_startlist')
        self.menu_race_result = b.get_object('menu_race_result')
        self.race_box = b.get_object('race_box')
        self.new_race_pop = b.get_object('menu_race_new_types')
        b.connect_signals(self)

        # run state
        self.scbwin = None
        self.running = True
        self.started = False
        self.curevent = None
        self.autorecurse = set()

        # connect UI log handlers
        _log.debug('Connecting interface log handlers')
        rootlogger = logging.getLogger()
        f = logging.Formatter(metarace.LOGFORMAT)
        self.sh = uiutil.statusHandler(self.status, self.context)
        self.sh.setFormatter(f)
        self.sh.setLevel(logging.INFO)  # show info+ on status bar
        rootlogger.addHandler(self.sh)
        self.lh = uiutil.textViewHandler(self.log_buffer, self.log_view,
                                             self.log_scroll)
        self.lh.setFormatter(f)
        self.lh.setLevel(logging.INFO)  # show info+ in text view
        rootlogger.addHandler(self.lh)

        # get rider db and pack into scrolled pane
        _log.debug('TODO: Add riderdb')
        self.rdb = riderdb.riderdb()
        #self.ridermap = {}
        #b.get_object('rider_box').add(self.rdb.mkview(ucicode=True, note=True))

        # get event db and pack into scrolled pane
        _log.debug('TODO: Add eventdb')
        self.edb = eventdb.eventdb()
        #self.edb.set_startlist_cb(self.eventdb_cb, 'startlist')
        #self.edb.set_result_cb(self.eventdb_cb, 'result')
        #self.edb.set_program_cb(self.eventdb_cb, 'program')
        #b.get_object('event_box').add(self.edb.mkview())
        #self.edb.set_evno_change_cb(self.race_evno_change)
        # connect each of the race menu types if present in builder
        #for etype in self.edb.racetypes:
            #lookup = 'mkrace_' + etype.replace(' ', '_')
            #mi = b.get_object(lookup)
            #if mi is not None:
                #mi.connect('activate', self.menu_race_make_activate_cb, etype)

        # start timers
        _log.debug('Starting meet timers')
        GLib.timeout_add_seconds(1, self.menu_clock_timeout)
        GLib.timeout_add(50, self.timeout)


def edit_defaults():
    """Run a sysconf editor dialog"""
    metarace.sysconf.add_section('trackmeet', _CONFIG_SCHEMA)
    metarace.sysconf.add_section('export', _EXPORT_SCHEMA)
    metarace.sysconf.add_section('telegraph', _TG_SCHEMA)
    metarace.sysconf.add_section('sender', _SENDER_SCHEMA)
    metarace.sysconf.add_section('timy', _TIMY_SCHEMA)
    cfgres = uiutil.options_dlg(title='Edit Default Configuration',
                                sections={
                                    'roadmeet': {
                                        'title': 'Meet',
                                        'schema': _CONFIG_SCHEMA,
                                        'object': metarace.sysconf,
                                    },
                                    'export': {
                                        'title': 'Export',
                                        'schema': _EXPORT_SCHEMA,
                                        'object': metarace.sysconf,
                                    },
                                    'telegraph': {
                                        'title': 'Telegraph',
                                        'schema': _TG_SCHEMA,
                                        'object': metarace.sysconf,
                                    },
                                    'sender': {
                                        'title': 'Sender',
                                        'schema': _SENDER_SCHEMA,
                                        'object': metarace.sysconf,
                                    },
                                    'timy': {
                                        'title': 'Timy',
                                        'schema': _TIMY_SCHEMA,
                                        'object': metarace.sysconf,
                                    },
                                })

    # check for sysconf changes:
    syschange = False
    for sec in cfgres:
        for key in cfgres[sec]:
            if cfgres[sec][key][0]:
                syschange = True
                break
    if syschange:
        backup = metarace.SYSCONF + '.bak'
        _log.info('Backing up old defaults to %r', backup)
        try:
            if os.path.exists(backup):
                os.unlink(backup)
            os.link(metarace.SYSCONF, backup)
        except Exception as e:
            _log.warning('%s saving defaults backup: %s', e.__class__.__name__,
                         e)
        _log.info('Edit default: Saving sysconf to %r', metarace.SYSCONF)
        with metarace.savefile(metarace.SYSCONF, perm=0o600) as f:
            metarace.sysconf.write(f)
    else:
        _log.info('Edit default: No changes to save')
    return 0


def createmeet():
    """Create a new empty meet folder"""
    ret = None
    count = 0
    dname = 'track_' + tod.datetime.now().date().isoformat()
    cname = dname
    while count < 100:
        mpath = os.path.join(metarace.DATA_PATH, cname)
        if not os.path.exists(mpath):
            os.makedirs(mpath)
            _log.info('Created empty meet folder: %r', mpath)
            ret = mpath
            break
        count += 1
        cname = dname + '_%02d' % (count)
    if ret is None:
        _log.error('Unable to create empty meet folder')
    return ret


def main():
    """Run the track meet application as a console script."""
    chk = Gtk.init_check()
    if not chk[0]:
        print('Unable to init Gtk display')
        sys.exit(-1)

    # attach a console log handler to the root logger
    ch = logging.StreamHandler()
    ch.setLevel(metarace.LOGLEVEL)
    fh = logging.Formatter(metarace.LOGFORMAT)
    ch.setFormatter(fh)
    logging.getLogger().addHandler(ch)

    # try to set the menubar accel and logo
    try:
        lfile = metarace.default_file(metarace.LOGO)
        Gtk.Window.set_default_icon_from_file(lfile)
        mset = Gtk.Settings.get_default()
        mset.set_property('gtk-menu-bar-accel', 'F24')
    except Exception as e:
        _log.debug('%s setting property: %s', e.__class__.__name__, e)

    doconfig = False
    configpath = None
    if len(sys.argv) > 2:
        _log.error('Usage: trackmeet [PATH]')
        sys.exit(1)
    elif len(sys.argv) == 2:
        if sys.argv[1] == '--edit-default':
            doconfig = True
            configpath = metarace.DEFAULTS_PATH
            _log.debug('Edit defaults, configpath: %r', configpath)
        else:
            configpath = sys.argv[1]
    else:
        configpath = createmeet()
    configpath = metarace.config_path(configpath)
    if configpath is None:
        _log.debug('Missing path, command: %r', sys.argv)
        _log.error('Error opening meet')
        if not os.isatty(sys.stdout.fileno()):
            uiutil.messagedlg(
                message='Error opening meet.',
                title='roadmeet: Error',
                subtext='Trackmeet was unable to open a meet folder.')
        sys.exit(-1)

    lf = metarace.lockpath(configpath)
    if lf is None:
        _log.error('Unable to lock meet config, already in use')
        if not os.isatty(sys.stdout.fileno()):
            uiutil.messagedlg(
                message='Meet folder is locked.',
                title='roadmeet: Locked',
                subtext=
                'Another application has locked the meet folder for use.')
        sys.exit(-1)
    _log.debug('Entering meet folder %r', configpath)
    os.chdir(configpath)
    metarace.init()
    if doconfig:
        return edit_defaults()
    else:
        app = trackmeet(lf)
        mp = configpath
        if mp.startswith(metarace.DATA_PATH):
            mp = mp.replace(metarace.DATA_PATH + '/', '')
        app.status.push(app.context, 'Meet Folder: ' + mp)
        app.loadconfig()
        app.window.show()
        app.start()
        return Gtk.main()
