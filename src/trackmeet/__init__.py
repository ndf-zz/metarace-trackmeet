# SPDX-License-Identifier: MIT
"""Timing and data handling application wrapper for track events."""

import sys
import gi
import logging
import metarace
from metarace import htlib
import csv
import os
import json
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
from .sender import sender, OVERLAY_CLOCK, _CONFIG_SCHEMA as _SENDER_SCHEMA
from .gemini import gemini
from . import uiutil
from . import scbwin
from . import eventdb
from . import race
from . import ps
from . import f200
from . import ittt
from . import sprnd
from . import classification

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
    'title': {
        'prompt': 'Title:',
        'hint': 'Meet title',
        'attr': 'title',
        'default': '',
    },
    'subtitle': {
        'prompt': 'Subtitle:',
        'hint': 'Meet subtitle',
        'attr': 'subtitle',
        'default': '',
    },
    'host': {
        'prompt': 'Host:',
        'hint': 'Text for the meet host / sponsor line',
        'attr': 'host',
        'default': '',
    },
    'document': {
        'prompt': 'Location:',
        'hint': 'Text for the meet location / document line',
        'attr': 'document',
        'default': '',
    },
    'date': {
        'prompt': 'Date:',
        'hint': 'Date of the meet as human-readable text',
        'attr': 'date',
        'default': '',
    },
    'pcp': {
        'prompt': 'PCP:',
        'hint': 'Name of the president of the commissaires panel',
        'attr': 'pcp',
        'default': '',
    },
    'organiser': {
        'prompt': 'Organiser:',
        'hint': 'Name of the meet organiser',
        'attr': 'organiser',
        'default': '',
    },
    'sectlen': {
        'control': 'section',
        'prompt': 'Track Length',
    },
    'tracklen_n': {
        'prompt': 'Numerator:',
        'control': 'short',
        'type': 'int',
        'attr': 'tracklen_n',
        'subtext': '(metres)',
        'default': 250,
    },
    'tracklen_d': {
        'prompt': 'Denominator:',
        'control': 'short',
        'type': 'int',
        'attr': 'tracklen_d',
        'subtext': '(laps)',
        'default': 1,
    },
    'secres': {
        'control': 'section',
        'prompt': 'Results',
    },
    'provisional': {
        'prompt': 'Program:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Provisional?',
        'hint': 'Mark program and results provisional',
        'attr': 'provisional',
        'default': True,
    },
    'communiques': {
        'prompt': 'Communiqu\u00e9s:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Number?',
        'hint': 'Assign numbers to all reports',
        'attr': 'communiques',
        'default': False,
    },
    'showevno': {
        'prompt': 'Event Nos:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Show?',
        'hint': 'Display event numbers in results',
        'attr': 'showevno',
        'default': True,
    },
    'clubmode': {
        'prompt': 'Club mode:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Auto add riders?',
        'hint': 'Automatically add unknown riders to meet',
        'attr': 'clubmode',
        'default': False,
    },
    'sectele': {
        'control': 'section',
        'prompt': 'Telegraph',
    },
    'anntopic': {
        'prompt': 'Announce:',
        'hint': 'Base topic for announcer messages',
        'attr': 'anntopic',
    },
    'sechw': {
        'control': 'section',
        'prompt': 'Hardware',
    },
    'timerport': {
        'prompt': 'Chronometer:',
        'hint': 'Chronometer port eg: /dev/ttyS0',
        'defer': True,
        'attr': 'timerport',
    },
    'timerprint': {
        'prompt': '',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Enable printer?',
        'hint': 'Enable chronoprinter',
        'attr': 'timerprint',
        'default': False,
    },
    'scbport': {
        'prompt': 'Scoreboard:',
        'hint': 'Caprica/DHI scoreboard eg: DEFAULT',
        'defer': True,
        'attr': 'scbport',
    },
    'gemport': {
        'prompt': 'Gemini Board:',
        'hint': 'Numeric display board port eg: /dev/ttyUSB1',
        'defer': True,
        'attr': 'gemport',
    },
    'secexp': {
        'control': 'section',
        'prompt': 'Export',
    },
    'mirrorcmd': {
        'prompt': 'Command:',
        'hint': 'Command to run if export script is enabled',
        'attr': 'mirrorcmd',
    },
    'mirrorpath': {
        'prompt': 'Path:',
        'hint': 'Result export path',
        'attr': 'mirrorpath',
    },
    'shortname': {
        'prompt': 'Short Name:',
        'hint': 'Short meet name on web export header',
        'attr': 'shortname',
    },
    'eventcode': {
        'prompt': 'Event Code:',
        'hint': 'Event code saved in reports',
        'attr': 'eventcode',
    },
    # deprecated config elements
    'linkbase': {
        'attr': 'linkbase',
        'control': 'none',
        'default': '.',
    },
}

# Temporary
_EVENT_SCHEMA = {
    'evid': {
        'prompt': 'Event No:',
        'control': 'short',
        'attr': 'evid',
        'defer': True,
        'default': '',
    },
    'pref': {
        'prompt': 'Prefix:',
        'attr': 'pref',
        'defer': True,
        'default': '',
    },
    'info': {
        'prompt': 'Information:',
        'attr': 'info',
        'defer': True,
        'default': '',
    },
    'type': {
        'prompt': 'Type Handler:',
        'control': 'short',
        'attr': 'type',
        'defer': True,
        'default': '',
    },
    'depe': {
        'prompt': 'Depends on:',
        'attr': 'depe',
        'defer': True,
        'default': '',
    },
    'resu': {
        'prompt': 'Include in:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Results?',
        'attr': 'resu',
        'defer': True,
        'default': True,
    },
    'inde': {
        'prompt': '',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Event Index?',
        'attr': 'inde',
        'defer': True,
        'default': False,
    },
    'prin': {
        'prompt': '',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Printed Program?',
        'attr': 'prin',
        'defer': True,
        'default': False,
    },
    'plac': {
        'prompt': 'Placeholders:',
        'control': 'short',
        'type': 'int',
        'attr': 'plac',
        'defer': True,
    },
    'sess': {
        'prompt': 'Session ID:',
        'control': 'short',
        'attr': 'sess',
        'defer': True,
        'default': '',
    },
    'laps': {
        'prompt': 'Lap Count:',
        'control': 'short',
        'type': 'int',
        'attr': 'laps',
        'defer': True,
    },
    'dist': {
        'prompt': 'Distance text:',
        'attr': 'dist',
        'defer': True,
        'default': '',
    },
    'prog': {
        'prompt': 'Progression text:',
        'attr': 'prog',
        'defer': True,
        'default': '',
    },
    'reco': {
        'prompt': 'Record text:',
        'attr': 'reco',
        'defer': True,
        'default': '',
    },
    'seri': {
        'prompt': 'Series',
        'control': 'short',
        'attr': 'seri',
        'defer': True,
        'default': '',
    },
    'refe': {
        'prompt': 'Reference No:',
        'control': 'short',
        'attr': 'refe',
        'defer': True,
        'default': '',
    },
    'evov': {
        'prompt': 'Event no override:',
        'control': 'short',
        'attr': 'evov',
        'defer': True,
        'default': '',
    },
}


def mkrace(meet, event, ui=True):
    """Return a race object of the correct type."""
    ret = None
    etype = event[u'type']
    if etype in [
            'indiv tt', 'indiv pursuit', 'pursuit race', 'team pursuit',
            'team pursuit race'
    ]:
        ret = ittt.ittt(meet, event, ui)
    elif etype in [u'points', u'madison', u'omnium']:
        ret = ps.ps(meet, event, ui)
    elif etype == u'classification':
        ret = classification.classification(meet, event, ui)
    elif etype in [u'flying 200', u'flying lap']:
        ret = f200.f200(meet, event, ui)
    ##elif etype in [u'hour']:
    ##ret = hour.hourrec(meet, event, ui)
    elif etype in [u'sprint round', u'sprint final']:
        ret = sprnd.sprnd(meet, event, ui)
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
        self.menu_clock.clicked()

    def menu_meet_properties_cb(self, menuitem, data=None):
        """Edit meet properties."""
        metarace.sysconf.add_section('export', _EXPORT_SCHEMA)
        metarace.sysconf.add_section('telegraph', _TG_SCHEMA)
        metarace.sysconf.add_section('sender', _SENDER_SCHEMA)
        metarace.sysconf.add_section('timy', _TIMY_SCHEMA)
        cfgres = uiutil.options_dlg(window=self.window,
                                    title='Meet Properties',
                                    sections={
                                        'meet': {
                                            'title': 'Meet',
                                            'schema': _CONFIG_SCHEMA,
                                            'object': self,
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
                                            'title': 'Scoreboard',
                                            'schema': _SENDER_SCHEMA,
                                            'object': metarace.sysconf,
                                        },
                                        'timy': {
                                            'title': 'Timy',
                                            'schema': _TIMY_SCHEMA,
                                            'object': metarace.sysconf,
                                        },
                                    })

        # check for sysconf changes
        syschange = False
        tgchange = False
        timerchange = False
        scbchange = False
        for sec in ('export', 'timy', 'telegraph', 'sender'):
            for key in cfgres[sec]:
                if cfgres[sec][key][0]:
                    syschange = True
                    if sec == 'telegraph':
                        tgchange = True
                    elif sec == 'timy':
                        timerchange = True
                    elif sec == 'sender':
                        scbchange = True

        if syschange:
            _log.info('Saving config updates to meet folder')
            with metarace.savefile(metarace.SYSCONF, perm=0o600) as f:
                metarace.sysconf.write(f)

        # reset telegraph connection if required
        if tgchange:
            _log.info('Re-start telegraph')
            newannounce = telegraph()
            newannounce.setcb(self._controlcb)
            newannounce.start()
            oldannounce = self.announce
            self.announce = newannounce
            oldannounce.exit()

        # reset timer connection if required
        if timerchange:
            _log.info('Re-start timer')
            newtimy = timy()
            newtimy.setcb(self._timercb)
            newtimy.start()
            oldtimy = self.main_timer
            self.main_timer = newtimy
            oldtimy.exit()

        # reset scb connection if required
        if scbchange:
            _log.info('Re-start scb')
            self.scbwin = None
            oldscb = self.scb
            self.scb = sender()
            self.scb.start()
            oldscb.exit()

        res = cfgres['meet']
        # handle a change in announce topic
        if res['anntopic'][0] or tgchange:
            otopic = res['anntopic'][1]
            if otopic:
                self.announce.unsubscribe('/'.join((otopic, 'control', '#')))
            if self.anntopic:
                self.announce.subscribe('/'.join(
                    (self.anntopic, 'control', '#')))

        # reset timer port
        if res['timerport'][0] or timerchange:
            self.menu_timing_reconnect_activate_cb(None)

        # reset scb and or gemini if required
        if res['scbport'][0] or res['gemport'][0] or scbchange:
            self.menu_scb_connect_activate_cb(None)

        # always re-set title
        self.set_title()

    def menu_meet_quit_cb(self, menuitem, data=None):
        """Quit the track meet application."""
        self.running = False
        self.window.destroy()

    def report_strings(self, rep):
        """Copy meet information into the supplied report."""
        rep.strings['title'] = self.title
        rep.strings['host'] = self.host
        rep.strings['datestr'] = strops.promptstr('Date:', self.date)
        rep.strings['commstr'] = strops.promptstr('PCP:', self.pcp)
        rep.strings['orgstr'] = strops.promptstr('Organiser: ', self.organiser)
        rep.strings['diststr'] = self.document

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
        rep.strings['subtitle'] = (self.subtitle + ' ' + subtitle).strip()
        rep.strings['docstr'] = docstr
        for sec in sections:
            rep.add_section(sec)

        # write out to files if exportfile set
        if exportfile:
            ofile = os.path.join(EXPORTPATH, exportfile + '.pdf')
            with metarace.savefile(ofile, mode='b') as f:
                rep.output_pdf(f)
            ofile = os.path.join(EXPORTPATH, exportfile + '.xls')
            with metarace.savefile(ofile, mode='b') as f:
                rep.output_xls(f)
            ofile = os.path.join(EXPORTPATH, exportfile + '.json')
            with metarace.savefile(ofile) as f:
                rep.output_json(f)
            lb = ''
            lt = []
            if self.mirrorpath:
                lb = os.path.join(self.linkbase, exportfile)
                lt = ['pdf', 'xls']
            ofile = os.path.join(EXPORTPATH, exportfile + '.html')
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
                _log.debug('Found allocation: %r -> %r', ret, lookup)
                break
            else:
                noset.add(self.commalloc[c])
        if ret is None:  # not yet allocated
            while True:
                ret = str(cnt)
                if ret not in noset:
                    self.commalloc[lookup] = ret  # write back
                    _log.debug('Add allocation: %r -> %r', ret, lookup)
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
                _log.error('Unknown type in eventdb calback: %r', reptype)
            h = None
            secs.append(report.pagebreak())
        if len(secs) > 0:
            reporthash = reptype + ', '.join(evlist)
            if self.communiques:
                commno = self.find_communique(reporthash)
                if commno is not None:
                    reptypestr = ('Communiqu\u00e9 ' + commno + ': ' +
                                  reptypestr)
                ## TODO: revision and signature
                ## signature
                ##secs.append(msgsec)
            self.print_report(secs,
                              docstr=reptypestr,
                              exportfile='trackmeet_' + reptype)
        else:
            _log.info('%r callback: Nothing to report', reptype)
        return False

    def decision_format(self, decision):
        """Crudely macro format a commissaire decision string"""
        ret = []
        for line in decision.split('\n'):
            if line:
                ol = []
                for word in line.split():
                    if word.startswith('r:'):
                        punc = ''
                        if not word[-1].isalnum():
                            punc = word[-1]
                            word = word[0:-1]
                        rep = word
                        look = word.split(':', 1)[-1]
                        _log.debug('Look up rider: %r', look)
                        rid = self.rdb.get_id(look)
                        if rid is not None:
                            rep = self.rdb[rid].name_bib()
                        ol.append(rep + punc)
                    elif word.startswith('t:'):
                        punc = ''
                        if not word[-1].isalnum():
                            punc = word[-1]
                            word = word[0:-1]
                        rep = word
                        look = word.split(':', 1)[-1]
                        _log.debug('Look up team: %r', look)
                        rid = self.rdb.get_id(look, 'team')
                        if rid is not None:
                            rep = self.rdb[rid]['first'] + ' (' + look.upper(
                            ) + ')'
                        ol.append(rep + punc)
                    elif word.startswith('d:'):
                        punc = ''
                        if not word[-1].isalnum():
                            punc = word[-1]
                            word = word[0:-1]
                        rep = word
                        look = word.split(':', 1)[-1]
                        _log.debug('Look up ds: %r', look)
                        rid = self.rdb.get_id(look, 'ds')
                        if rid is not None:
                            rep = self.rdb[rid].fitname(48)
                        ol.append(rep + punc)
                    else:
                        ol.append(word)
                ret.append(' '.join(ol))
        return '\n'.join(ret)

    def decision_section(self, decisions=[]):
        """Return an officials decision section"""
        ret = report.bullet_text('decisions')
        if decisions:
            ret.heading = 'Decisions of the commissaires panel'
            for decision in decisions:
                if decision:
                    ret.lines.append((None, self.decision_format(decision)))
        return ret

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

    def menu_race_decisions_activate_cb(self, menuitem, data=None):
        """Edit decisions on open race if possible."""
        if self.curevent is not None:
            self.curevent.decisions = uiutil.decisions_dlg(
                self.window, self.curevent.decisions)

    def menu_race_run_activate_cb(self, menuitem=None, data=None):
        """Open currently selected event."""
        eh = self.event_getselected()
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
                self.select_event(nh)
            else:
                _log.warning('No next event to open')
        else:
            eh = self.event_getselected()
            if eh is not None:
                self.open_event(eh)
                self.select_event(eh)
            else:
                _log.warning('No next event to open')

    def select_event(self, event):
        """Find matching event in view and set selection"""
        for e in self._elm:
            if e[0] == event['evid']:
                self._elv.set_cursor(e.path, None, False)
                break

    def menu_race_prev_activate_cb(self, menuitem, data=None):
        """Open the previous event on the program."""
        if self.curevent is not None:
            ph = self.edb.getprevrow(self.curevent.event)
            if ph is not None:
                self.open_event(ph)
                self.select_event(ph)
            else:
                _log.warning('No previous event to open')
        else:
            eh = self.event_getselected()
            if eh is not None:
                self.open_event(eh)
                self.select_event(eh)
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
                    _log.info('Transferred autospec %r to event %r', spec,
                              self.curevent.evno)
                else:
                    self.addstarters(
                        self.curevent,
                        eventhdl,  # xfer starters
                        strops.reformat_biblist(starters))
                eventhdl['star'] = ''
            self.menu_race_properties.set_sensitive(True)
            self.menu_race_decisions.set_sensitive(True)
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
            _log.debug('Autospec group: %r', egroup)
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
                        h = None
                        #h.destroy()
                    else:
                        _log.warning('Autospec event not found: %r', evno)
                    self.autorecurse.remove(evno)
                else:
                    _log.debug('Ignoring loop in auto placelist: %r', evno)
            else:
                _log.warning('Ignoring erroneous autospec group: %r', egroup)
        ret = ''
        for place in sorted(places):
            ret += ' ' + '-'.join(places[place])
        ## TODO: append to [] then join
        _log.debug('Place set: %r', ret)
        return ret

    def autostart_riders(self, race, autospec='', infocol=None, final=True):
        """Try to fetch the startlist from race result info."""
        # infocol allows selection of seeding value for subsequent ruonds
        # possible values:
        #                   1 -> rank (ps/omnium, pursuit)
        #                   2 -> time (sprint)
        #                   3 -> info (handicap)
        # TODO: check default, maybe defer to None
        # TODO: IMPORTANT cache result gens for fast recall
        for egroup in autospec.split(';'):
            _log.debug('Autospec group: %r', egroup)
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
                        if h.finished:
                            for ri in h.result_gen():
                                if isinstance(ri[1],
                                              int) and ri[1] in placeset:
                                    rank = ri[1]
                                    if rank not in evplacemap:
                                        evplacemap[rank] = []
                                    seed = None
                                    if infocol is not None and infocol < len(
                                            ri):
                                        seed = ri[infocol]
                                    evplacemap[rank].append([ri[0], seed])
                        else:
                            _log.debug('Event %r not final', evno)
                        #h.destroy()
                        h = None
                        # maintain ordering of autospec
                        for p in placeset:
                            if p in evplacemap:
                                for ri in evplacemap[p]:
                                    race.addrider(ri[0], ri[1])
                    else:
                        _log.warning('Autospec event not found: %r', evno)
                    self.autorecurse.remove(evno)
                else:
                    _log.debug('Ignoring loop in auto startlist: %r', evno)
            else:
                _log.warning('Ignoring erroneous autospec group: %r', egroup)

    def close_event(self):
        """Close the currently opened race."""
        if self.curevent is not None:
            self.menu_race_properties.set_sensitive(False)
            self.menu_race_decisions.set_sensitive(False)
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
            delevent.saveconfig()
            #delevent.destroy()

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

        if cureventno:
            if cureventno in self.edb:
                self.open_event(self.edb[cureventno])
            else:
                _log.warning('Running event was removed from the event list')

    def menu_data_result_activate_cb(self, menuitem, data=None):
        """Export final result."""
        try:
            self.finalresult()  # TODO: Call in sep thread
        except Exception as e:
            _log.error('%s writing result: %s', e.__class__.__name__, e)
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
            r = None
            #r.destroy()

        filebase = 'result'
        self.print_report(sections,
                          'Results',
                          prov=provisional,
                          doprint=False,
                          exportfile=filebase.translate(strops.WEBFILE_UTRANS))

    def printprogram(self):
        r = report.report()
        subtitlestr = 'Program of Events'
        if self.subtitle:
            subtitlestr = self.subtitle + ' - ' + subtitlestr
        self.report_strings(r)
        r.strings['docstr'] = ''  # What should go here?
        r.strings['subtitle'] = subtitlestr

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
                h = None
                #h.destroy()

        filebase = 'program'
        ofile = os.path.join('export', filebase + '.pdf')
        with metarace.savefile(ofile, mode='b') as f:
            r.output_pdf(f, docover=True)
            _log.info('Exported pdf program to %r', ofile)
        ofile = os.path.join('export', filebase + '.html')
        with metarace.savefile(ofile) as f:
            r.output_html(f)
            _log.info('Exported html program to %r', ofile)
        ofile = os.path.join('export', filebase + '.xls')
        with metarace.savefile(ofile, mode='b') as f:
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
            _log.error('%s writing report: %s', e.__class__.__name__, e)
            raise

    def menu_data_update_activate_cb(self, menuitem, data=None):
        """Update meet, session, event and riders in external database."""
        try:
            _log.info('Exporting data.')
            self.updateindex()  # TODO: push into sep thread
        except Exception as e:
            _log.error('%s exporting event data: %s', e.__class__.__name__, e)
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
        self.updatenexprev()  # re-compute next/prev link struct
        # check for printed program link
        # check for final result link
        # check for timing log link
        # build index of events report
        if self.mirrorpath:
            orep = report.report()
            self.report_strings(orep)
            orep.strings['docstr'] = ''
            orep.strings['subtitle'] = self.subtitle
            orep.set_provisional(self.provisional)  # ! TODO
            orep.shortname = self.title
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

            pdata = {
                'title': self.title,
                'subtitle': self.subtitle,
                'host': self.host,
                'date': self.date,
                'location': self.document,
                'pcp': self.pcp,
                'organiser': self.organiser,
                'events': {}
            }
            sec = report.event_index('eventindex')
            sec.heading = 'Index of Events'
            #sec.subheading = Date?
            for eh in self.edb:
                if eh['inde']:  # include in index?
                    evno = eh['evid']
                    if eh['type'] in ['break', 'session']:
                        evno = None
                    referno = evno
                    target = None
                    if eh['refe']:  # overwrite ref no, even on specials
                        referno = eh['refe']
                        if referno != evno:
                            target = 'ev-' + str(evno).translate(
                                strops.WEBFILE_UTRANS)
                    linkfile = None
                    if referno:
                        linkfile = 'event_' + str(referno).translate(
                            strops.WEBFILE_UTRANS)
                    descr = ' '.join([eh['pref'], eh['info']]).strip()
                    extra = None  # STATUS INFO -> progress?
                    if eh['evov'] is not None and eh['evov'] != '':
                        evno = eh['evov'].strip()
                    sec.lines.append(
                        [evno, None, descr, extra, linkfile, target])
                    erec = {
                        'no': referno,
                        'prefix': eh['prefix'],
                        'info': eh['info'],
                        'laps': eh['laps'],
                        'distance': eh['dist'],
                        'progression': eh['prog'],
                        'handler': eh['type'],
                        'series': eh['seri'],
                    }
                    if eh['type'] and eh['type'] not in ['break']:
                        erec['startlist'] = linkfile + '_startlist.json'
                        erec['result'] = linkfile + '_result.json'
                    pdata['events'][eh['evid']] = erec
            orep.add_section(sec)
            basename = 'index'
            ofile = os.path.join(EXPORTPATH, basename + '.html')
            with metarace.savefile(ofile) as f:
                orep.output_html(f, linkbase=lb, linktypes=lt)
            jbase = basename + '.json'
            ofile = os.path.join(EXPORTPATH, jbase)
            with metarace.savefile(ofile) as f:
                orep.output_json(f)

            # dump out the json program
            basename = 'program'
            ofile = os.path.join(EXPORTPATH, basename + '.json')
            with metarace.savefile(ofile) as f:
                json.dump(pdata, f)

            # also dump out json riders list
            rdata = {}
            for r in self.rdb:
                rh = self.rdb[r]
                key = rh.get_bibstr()
                rdata[key] = {
                    'no': rh['no'],
                    'series': rh['series'],
                    'first': rh['first'],
                    'last': rh['last'],
                    'org': rh['org'],
                    'cat': rh['cat'],
                    'name': rh.resname(),
                    'uciid': rh['uciid'],
                }
            basename = 'riders'
            ofile = os.path.join(EXPORTPATH, basename + '.json')
            with metarace.savefile(ofile) as f:
                json.dump(rdata, f)

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
            self.mirror = mirror(localpath=os.path.join(EXPORTPATH, ''),
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

    def check_depends_dirty(self, evno, checked=None):
        """Recursively determine event dependencies"""
        _log.debug('depends: evno=%r, checked=%r', evno, checked)
        if checked is None:
            checks = set()
        else:
            checks = set(checked)
        checks.add(evno)

        ev = self.edb[evno]

        # scan any dependencies
        for dev in ev['depe'].split():
            if ev['dirty']:
                # other dirty dependencies will be collected by caller
                break
            if dev in checks:
                _log.debug('Circular dependency ignored')
            else:
                dep = self.check_depends_dirty(dev, checks)
                checks.add(dev)
                if dep:
                    ev['dirty'] = True
                    _log.debug('depends: %r set dirty by depend %r', evno, dev)

        _log.debug('depends: %r returns %r', evno, ev['dirty'])
        return ev['dirty']

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
                dirty = self.check_depends_dirty(evno)
                if dirty:
                    dord.append(key)  # maintains ordering
                    dmap[key] = [e, evno, etype, series, prefix, info, export]
            _log.debug('Marked %d events dirty', len(dord))

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

                startrep = r.startlist_report('startlist')
                startsec = None

                if self.mirrorpath and doexport:
                    orep = report.report()
                    orep.showcard = False
                    self.report_strings(orep)
                    orep.strings['subtitle'] = evstr
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
                    resrep = r.result_report()
                    ressec = None

                    # build combined html style report
                    for sec in resrep:
                        if sec.sectionid == 'result':
                            ressec = sec
                    for sec in startrep:
                        if sec.sectionid == 'startlist':
                            startsec = sec
                    if r.onestart:  # output result
                        outsec = resrep
                    else:
                        outsec = startrep
                    for sec in outsec:
                        orep.add_section(sec)
                    basename = 'event_' + str(evno).translate(
                        strops.WEBFILE_UTRANS)
                    ofile = os.path.join(EXPORTPATH, basename + '.html')
                    with metarace.savefile(ofile) as f:
                        orep.output_html(f)
                    jbase = basename + '.json'
                    ofile = os.path.join(EXPORTPATH, jbase)
                    with metarace.savefile(ofile) as f:
                        orep.output_json(f)

                    # startlist data file !!!
                    sdata = {
                        'id': e['evid'],
                        'reference': e['refe'],
                        'event': e['evov'],
                        'prefix': e['pref'],
                        'info': e['info'],
                        'laps': e['laps'],
                        'diststr': e['dist'],
                        'progression': e['prog'],
                        'footer': e['reco'],
                        'startlist': []
                    }
                    if startsec is not None and startsec.lines:
                        for l in startsec.lines:
                            if l[1]:
                                startdat = {
                                    'no': l[1],
                                    'rider': l[2],
                                    'info': l[3]
                                }
                                sdata['startlist'].append(startdat)
                    ofile = os.path.join(EXPORTPATH,
                                         basename + '_startlist.json')
                    with metarace.savefile(ofile) as f:
                        json.dump(sdata, f)

                    # result data file
                    rdata = {
                        'id': e['evid'],
                        'reference': e['refe'],
                        'event': e['evov'],
                        'prefix': e['pref'],
                        'info': e['info'],
                        'laps': e['laps'],
                        'diststr': e['dist'],
                        'progression': e['prog'],
                        'footer': e['reco'],
                        'status': r.standingstr(),
                        'result': []
                    }
                    if ressec is not None and ressec.lines:
                        for l in ressec.lines:
                            if l[0]:
                                resdat = {
                                    'rank': l[0],
                                    'no': l[1],
                                    'rider': l[2],
                                    'info': l[3],
                                    'time': l[4],
                                    'points': l[5]
                                }
                                rdata['result'].append(resdat)
                    ofile = os.path.join(EXPORTPATH, basename + '_result.json')
                    with metarace.savefile(ofile) as f:
                        json.dump(rdata, f)

                r = None
                #r.destroy()
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
        self.scb.sendmsg(OVERLAY_CLOCK)
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
        self.main_timer.setport(self.timerport)
        if self.timerport:
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
         line3) = strops.titlesplit(self.title + ' ' + self.subtitle,
                                    self.scb.linelen)
        self.scbwin = scbwin.scbclock(self.scb,
                                      line1,
                                      line2,
                                      line3,
                                      locstr=self.document)
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
                    _log.debug('Removing completed export thread.')

            if self.exporter is not None:
                if not self.exporter.is_alive():
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
        self.main_timer.printline(self.title)
        self.main_timer.printline(self.subtitle)
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
            ret = ' '.join([self.title, self.subtitle]).strip()
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
                          ' '.join([self.title, self.subtitle,
                                    self.date]).strip(), ANNOUNCE_LINELEN - 2,
                          'c')))

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
        self.window.set_title('trackmeet: ' +
                              ' '.join([self.title, self.subtitle]).strip())
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
                    t = tod.now(chan=str(key), source='MAN')
                    self._timercb(t)
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

    def _timercb(self, evt, data=None):
        _log.debug('Timer: %r %r', evt, data)
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
            self.main_timer.setcb(self._timercb)
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
        cw.add_section('trackmeet', _CONFIG_SCHEMA)
        if self.curevent is not None and self.curevent.winopen:
            self.save_curevent()
            cw.set('trackmeet', 'curevent', self.curevent.evno)
        elif lastevent is not None:
            cw.set('trackmeet', 'curevent', lastevent)
        cw.set('trackmeet', 'commalloc', self.commalloc)
        cw.import_section('trackmeet', self)
        cw.set('trackmeet', 'id', TRACKMEET_ID)
        with metarace.savefile(CONFIGFILE) as f:
            cw.write(f)
        self.rdb.save('riders.csv')
        self.edb.save('events.csv')
        _log.info('Meet configuration saved')

    def loadconfig(self):
        """Load meet config from disk."""
        cr = jsonconfig.config(
            {'trackmeet': {
                'commalloc': {},
                'curevent': None,
            }})
        cr.add_section('trackmeet', _CONFIG_SCHEMA)

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

        cr.merge(metarace.sysconf, 'trackmeet')
        cr.load(CONFIGFILE)
        cr.export_section('trackmeet', self)

        if self.timerport:
            self.main_timer.setport(self.timerport)
        if self.gemport:
            self.gemini.setport(self.gemport)

        # reset announcer topic
        if self.anntopic:
            self.announce.subscribe('/'.join((self.anntopic, 'control', '#')))

        # connect DHI scoreboard
        if self.scbport:
            self.scb.setport(self.scbport)

        self.set_title()

        # communique allocations -> fixed once only
        self.commalloc = cr.get('trackmeet', 'commalloc')

        # check track length
        if self.tracklen_n > 0 and self.tracklen_n < 5500 and self.tracklen_d > 0 and self.tracklen_d < 10:
            _log.debug('Track length %r/%r', self.tracklen_n, self.tracklen_d)
        else:
            _log.warning('Ignoring invalid track length')
            self.tracklen_n = 250
            self.tracklen_d = 1

        self.rdb.clear(notify=False)
        self.edb.clear()
        self.edb.load('events.csv')
        self.rdb.load('riders.csv')

        # make sure export path exists
        if not os.path.exists(EXPORTPATH):
            os.mkdir(EXPORTPATH)
            _log.info('Created export path: %r', EXPORTPATH)

        # re-open current event
        cureventno = cr.get('trackmeet', 'curevent')
        if cureventno and cureventno in self.edb:
            self.open_event(self.edb[cureventno])

        # check and warn of config mismatch
        cid = cr.get_value('trackmeet', 'id')
        if cid is not None and cid != TRACKMEET_ID:
            _log.warning('Meet config mismatch: %r != %r', cid, TRACKMEET_ID)

    def menu_import_riders_activate_cb(self, menuitem, data=None):
        """Add riders to database."""
        sfile = uiutil.chooseCsvFile(title='Select rider file to import',
                                     parent=self.window,
                                     path='.')
        if sfile is not None:
            try:
                count = self.rdb.load(sfile, overwrite=True)
                _log.info('Imported %d rider entries from %r', count, sfile)
            except Exception as e:
                _log.error('%s importing riders: %s', e.__class__.__name__, e)
        else:
            _log.debug('Import riders cancelled')

    def rider_edit_cb(self, menuitem, data=None):
        """Edit properties of currently selected entry in riderdb"""
        if self._cur_rider_sel is not None and self._cur_rider_sel in self.rdb:
            doreopen = False
            rider = self._cur_rider_sel
            dbr = self.rdb[rider]
            schema = dbr.get_schema()
            rtype = schema['rtype']['prompt']
            short = 'Edit %s %s' % (rtype, dbr.get_bibstr())
            res = uiutil.options_dlg(window=self.window,
                                     title=short,
                                     sections={
                                         'rdb': {
                                             'title': 'Rider',
                                             'schema': schema,
                                             'object': dbr,
                                         },
                                     })
            if rtype == 'Team':
                # Patch the org value which is not visible, without notify
                dbr.set_value('org', dbr['no'].upper())
            if res['rdb']['no'][0] or res['rdb']['series'][0]:
                # change of number or series requires some care
                self._cur_rider_sel = None
                newrider = self.rdb.add_rider(dbr,
                                              notify=False,
                                              overwrite=False)
                if rtype == 'Category':
                    if uiutil.questiondlg(
                            window=self.window,
                            question='Update rider categories?',
                            subtext=
                            'Riders in the old category will be updated to the new one',
                            title='Update Cats?'):
                        self.rdb.update_cats(res['rdb']['no'][1],
                                             res['rdb']['no'][2],
                                             notify=False)
                        # and current event
                        if self.curevent is not None:
                            if res['rdb']['no'][1].upper(
                            ) in self.curevent.cats:
                                nc = []
                                for c in self.curevent.cats:
                                    if c == res['rdb']['no'][1].upper():
                                        nc.append(res['rdb']['no'][2].upper())
                                    else:
                                        nc.append(c)
                                self.curevent.loadcats(nc)
                                doreopen = True
                else:
                    # update curevent
                    if self.curevent is not None:
                        if self.curevent.getrider(res['rdb']['no'][1],
                                                  res['rdb']['series'][1]):
                            # rider was in event, add new one
                            self.curevent.addrider(dbr['no'], dbr['series'])
                            if self.curevent.timerstat == 'idle':
                                self.curevent.delrider(res['rdb']['no'][1],
                                                       res['rdb']['series'][1])
                            else:
                                _log.warning(
                                    'Changed rider number %r => %r, check data',
                                    res['rdb']['no'][1], res['rdb']['no'][2])

                # del triggers a global notify
                del (self.rdb[rider])

                # then try to select the modified row
                GLib.idle_add(self.select_row, newrider)

                # then reopen curevent if flagged after notify
                if doreopen:
                    GLib.idle_add(self.event_reload)
            else:
                # notify meet and event of any changes, once
                for k in res['rdb']:
                    if res['rdb'][k][0]:
                        dbr.notify()
                        break

    def rider_lookup_cb(self, menuitem, data=None):
        _log.info('Rider lookup not yet enabled')

    def rider_delete_cb(self, menuitem, data=None):
        """Delete currently selected entry from riderdb"""
        if self._cur_rider_sel is not None and self._cur_rider_sel in self.rdb:
            dbr = self.rdb[self._cur_rider_sel]
            tv = []
            series = dbr['series']
            if series == 'cat':
                tv.append('Category')
                tv.append(dbr['no'].upper())
                tv.append(':')
                tv.append(dbr['first'])
            elif series == 'team':
                tv.append('Team')
                tv.append(dbr['no'].upper())
                tv.append(':')
                tv.append(dbr['first'])
            elif series == 'ds':
                tv.append('DS')
                tv.append(dbr.listname())
            elif series == 'spare':
                tv.append('Spare Bike')
                tv.append(dbr['no'])
                tv.append(dbr['org'])
            else:
                tv.append('Rider')
                tv.append(dbr.get_bibstr())
                tv.append(dbr.listname())
                if dbr['cat']:
                    tv.append(dbr['cat'].upper())
            short = ' '.join(tv[0:2])
            text = 'Delete %s?' % (short)
            info = 'This action will permanently delete %s' % (' '.join(tv))
            if uiutil.questiondlg(window=self.window,
                                  question=text,
                                  subtext=info,
                                  title='Delete?'):
                if self.curevent is not None:
                    if series == 'cat':
                        cat = dbr['no'].upper()
                        if cat in self.curevent.cats:
                            _log.warning('Deleted cat %s in open event', cat)
                    elif series not in ('ds', 'spare', 'team'):
                        self.curevent.delrider(dbr['no'], series)
                        _log.info('Remove rider %s from event', short)
                del (self.rdb[self._cur_rider_sel])
                _log.info('Deleted %s', short)
                self._cur_rider_sel = None
            else:
                _log.debug('Rider delete aborted')

    def rider_add_cb(self, menuitem, data=None):
        """Create a new rider entry and edit the content"""
        nser = ''
        dbr = riderdb.rider(series=nser)
        schema = dbr.get_schema()
        rtype = schema['rtype']['prompt']
        short = 'Create New %s' % (rtype)
        res = uiutil.options_dlg(window=self.window,
                                 title=short,
                                 sections={
                                     'rdb': {
                                         'title': 'Rider',
                                         'schema': schema,
                                         'object': dbr,
                                     },
                                 })
        chg = False
        for k in res['rdb']:
            if res['rdb'][k][0]:
                chg = True
                break
        if chg:
            rider = self.rdb.add_rider(dbr, overwrite=False)
            GLib.idle_add(self.select_row, rider)

    def select_row(self, rider):
        """Select rider view model if possible"""
        if rider in self.rdb:
            rdb = self.rdb[rider]
            model = self._rlm
            view = self._rlv
            found = False
            for r in model:
                if r[6] == rider:
                    view.set_cursor(r.path, None, False)
                    found = True
                    break
            if not found:
                _log.debug('Entry %r not found, unable to select', rider)
        return False

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

    def eventcb(self, event):
        """Handle a change in the event model"""
        if event is not None:
            e = self.edb[event]
            for lr in self._elm:
                if lr[0] == event:
                    lr[0] = e['evid']
                    lr[1] = e.event_info()
                    lr[2] = e.event_type()
                    lr[3] = e['evid']
                    found = True
                    break
            _log.debug('Edit event %r', e)
        else:
            self._elm.clear()
            for e in self.edb:
                elr = [e['evid'], e.event_info(), e.event_type(), e['evid']]
                self._elm.append(elr)
            _log.debug('Re-load event view')
        if self.curevent is not None:
            self.curevent.eventcb(event)

    def ridercb(self, rider):
        """Handle a change in the rider model"""
        if rider is not None:
            r = self.rdb[rider]
            # note: duplicate ids mangle series, so use series from rider
            series = r['series'].lower()
            if series != 'cat':
                found = False
                for lr in self._rlm:
                    if lr[6] == rider:
                        lr[2] = r.fitname(64)
                        lr[3] = r['org']
                        lr[4] = r['note']
                        lr[5] = htlib.escape(r.summary())
                        found = True
                        break
                if not found:
                    lr = [
                        rider[0], series,
                        r.fitname(64), r['org'], r['note'],
                        htlib.escape(r.summary()), rider
                    ]
                    self._rlm.append(lr)
        else:
            # assume entire map has to be rebuilt
            self._rlm.clear()
            for r in self.rdb:
                dbr = self.rdb[r]
                # note: duplicate ids mangle series, so use series from rider
                series = dbr['series'].lower()
                if series != 'cat':
                    rlr = [
                        r[0], series,
                        dbr.fitname(64), dbr['org'], dbr['note'],
                        htlib.escape(dbr.summary()), r
                    ]
                    self._rlm.append(rlr)
        if self.curevent is not None:
            self.curevent.ridercb(rider)

    def _rcb(self, rider):
        GLib.idle_add(self.ridercb, rider)

    def _ecb(self, event):
        if event is None:
            GLib.idle_add(self.eventcb, event)

    def _editcol_cb(self, cell, path, new_text, col):
        """Callback for editing a rider note"""
        new_text = new_text.strip()
        bib = self._rlm[path][0]
        series = self._rlm[path][1]
        self._rlm[path][col] = new_text
        r = self.rdb.get_rider(bib, series)
        if r is not None:
            if col == 3:
                if new_text != r['org']:
                    r['org'] = new_text
            elif col == 4:
                if new_text != r['note']:
                    r['note'] = new_text

    def event_getselected(self):
        """Return event for the currently selected row, or None."""
        ref = None
        model, plist = self._elv.get_selection().get_selected_rows()
        if len(plist) > 0:
            evno = self._elm[plist[0]][0]
            if evno in self.edb:
                ref = self.edb[evno]
            else:
                _log.error(u'Event %r in view not found in model', evno)
        return ref

    def event_popup_edit_cb(self, menuitem, data=None):
        """Edit event extended attributes."""
        evno = None
        ref = None
        model, plist = self._elv.get_selection().get_selected_rows()
        if len(plist) > 0:
            evno = self._elm[plist[0]][0]
            if evno in self.edb:
                ref = self.edb[evno]
            else:
                _log.error('Event %r in view not found in model', evno)
        if ref is None:
            _log.error('No event selected for edit')
            return False
        schema = _EVENT_SCHEMA
        short = 'Edit event %s' % (evno)
        res = uiutil.options_dlg(window=self.window,
                                 title=short,
                                 sections={
                                     'edb': {
                                         'title': 'Event',
                                         'schema': schema,
                                         'object': ref,
                                     },
                                 })
        _log.warning('TODO: Handle change in event number')
        for k in res['edb']:
            if res['edb'][k][0]:
                self._ecb(evno)
                break

    def event_popup_result_cb(self, menuitem, data=None):
        """Print event results."""
        sel = self._elv.get_selection()
        cnt = sel.count_selected_rows()
        # check for one selected
        if cnt == 0:
            _log.debug(u'No rows selected for result')
            return False

        # convert model iters into a list of event numbers
        (model, iters) = sel.get_selected_rows()
        elist = [model[i][0] for i in iters]

        # queue callback in main loop
        GLib.idle_add(self.eventdb_cb, elist, 'result')

    def event_popup_startlist_cb(self, menuitem, data=None):
        """Print event startlists."""
        sel = self._elv.get_selection()
        cnt = sel.count_selected_rows()
        # check for one selected
        if cnt == 0:
            _log.debug(u'No rows selected for result')
            return False

        # convert model iters into a list of event numbers
        (model, iters) = sel.get_selected_rows()
        elist = [model[i][0] for i in iters]

        # queue callback in main loop
        GLib.idle_add(self.eventdb_cb, elist, 'startlist')

    def event_popup_program_cb(self, menuitem, data=None):
        """Print event program."""
        sel = self._elv.get_selection()
        cnt = sel.count_selected_rows()
        # check for one selected
        if cnt == 0:
            _log.debug(u'No rows selected for result')
            return False

        # convert model iters into a list of event numbers
        (model, iters) = sel.get_selected_rows()
        elist = [model[i][0] for i in iters]

        # queue callback in main loop
        GLib.idle_add(self.eventdb_cb, elist, 'program')

    def event_popup_insert_cb(self, menuitem, data=None):
        """Add new empty row."""
        self.edb.add_empty()

    def event_popup_delete_cb(self, menuitem, data=None):
        """Delete selected events"""
        sel = self._elv.get_selection()
        cnt = sel.count_selected_rows()
        # check for one selected
        if cnt == 0:
            _log.debug(u'No rows selected for delete')
            return False

        # convert model iters into a list of event numbers
        (model, iters) = sel.get_selected_rows()
        elist = [model[i][0] for i in iters]

        msg = 'Delete selected events?'
        if sel.count_selected_rows() == 1:
            evt = self.edb[elist[0]]
            sep = ''
            ifstr = evt.event_info()
            if ifstr:
                sep = ': '
            evno = evt['evid']
            msg = ('Delete event ' + evno + sep + ifstr + '?')

        if uiutil.questiondlg(self.window, 'Delete events?', msg):
            for evt in elist:
                _log.debug(u'Deleting event %r', evt)
                del (self.edb[evt])
            self._ecb(None)

    def _event_button_press(self, view, event):
        """Handle mouse button event on event tree view"""
        if event.type == Gdk.EventType.BUTTON_PRESS:
            if event.button == Gdk.BUTTON_SECONDARY:
                self._cur_model = view.get_model()
                pathinfo = view.get_path_at_pos(int(event.x), int(event.y))
                if pathinfo is not None:
                    path, col, cellx, celly = pathinfo
                    sel = view.get_selection()
                    if sel is not None:
                        if sel.path_is_selected(path):
                            # pressed path is already in current selection
                            pass
                        else:
                            view.grab_focus()
                            view.set_cursor(path, col, False)
                        if sel.count_selected_rows() > 1:
                            # prepare context for multiple select
                            self._event_menu_edit.set_sensitive(False)
                        else:
                            # prepare context for single select
                            self._event_menu_edit.set_sensitive(True)

                        self._event_menu_del.set_sensitive(True)
                    else:
                        _log.error('Invalid selection ignored')
                        self._cur_rider_sel = None
                        self._event_menu_edit.set_sensitive(False)
                        self._event_menu_del.set_sensitive(False)
                else:
                    self._cur_rider_sel = None
                    self._event_menu_edit.set_sensitive(False)
                    self._event_menu_del.set_sensitive(False)
                self._event_menu.popup_at_pointer(None)
                return True
        return False

    def _view_button_press(self, view, event):
        """Handle mouse button event on tree view"""
        if event.type == Gdk.EventType.BUTTON_PRESS:
            if event.button == Gdk.BUTTON_SECONDARY:
                self._cur_model = view.get_model()
                pathinfo = view.get_path_at_pos(int(event.x), int(event.y))
                if pathinfo is not None:
                    path, col, cellx, celly = pathinfo
                    view.grab_focus()
                    view.set_cursor(path, col, False)
                    sel = view.get_selection().get_selected()
                    if sel is not None:
                        i = sel[1]
                        r = Gtk.TreeModelRow(self._cur_model, i)
                        self._cur_rider_sel = r[6]
                        self._rider_menu_edit.set_sensitive(True)
                        self._rider_menu_del.set_sensitive(True)
                    else:
                        _log.error('Invalid selection ignored')
                        self._cur_rider_sel = None
                        self._rider_menu_edit.set_sensitive(False)
                        self._rider_menu_del.set_sensitive(False)
                else:
                    self._cur_rider_sel = None
                    self._rider_menu_edit.set_sensitive(False)
                    self._rider_menu_del.set_sensitive(False)
                self._rider_menu.popup_at_pointer(None)
                return True
        return False

    def __init__(self, lockfile=None):
        """Meet constructor."""
        self.loghandler = None  # set in loadconfig to meet dir
        self.meetlock = lockfile
        self.title = ''
        self.host = ''
        self.subtitle = ''
        self.document = ''
        self.date = ''
        self.organiser = ''
        self.pcp = ''
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
        self.exportpending = False
        self.mirrorpath = ''  # default mirror path
        self.mirrorcmd = None
        self.shortname = ''
        self.eventcode = ''
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
        self.timerport = ''
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
        self.menu_clock = b.get_object('menu_clock')
        self.menu_clock.add(self.rfustat)
        self.rfustat.update('idle', '--')

        self.status = b.get_object('status')
        self.log_buffer = b.get_object('log_buffer')
        self.log_view = b.get_object('log_view')
        #self.log_view.modify_font(uiutil.LOGVIEWFONT)
        self.log_scroll = b.get_object('log_box').get_vadjustment()
        self.context = self.status.get_context_id('metarace meet')
        self.menu_race_info = b.get_object('menu_race_info')
        self.menu_race_properties = b.get_object('menu_race_properties')
        self.menu_race_decisions = b.get_object('menu_race_decisions')
        self.menu_race_close = b.get_object('menu_race_close')
        self.menu_race_abort = b.get_object('menu_race_abort')
        self.menu_race_startlist = b.get_object('menu_race_startlist')
        self.menu_race_result = b.get_object('menu_race_result')
        self.race_box = b.get_object('race_box')
        self.new_race_pop = b.get_object('menu_race_new_types')

        # setup context menu handles
        self._rider_menu = b.get_object('rider_context')
        self._rider_menu_edit = b.get_object('rider_edit')
        self._rider_menu_lookup = b.get_object('rider_lookup')
        self._rider_menu_del = b.get_object('rider_del')
        self._cur_rider_sel = None
        self._event_menu = b.get_object('event_context')
        self._event_menu_edit = b.get_object('event_edit')
        self._event_menu_del = b.get_object('event_delete')
        self._cur_model = None

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

        # Build a rider list store and view
        self._rlm = Gtk.ListStore(
            str,  # no 0
            str,  # series 1
            str,  # name 2
            str,  # org 3
            str,  # note 4
            str,  # tooltip 5
            object,  # rider ref 6
        )
        t = Gtk.TreeView(self._rlm)
        t.set_reorderable(True)
        t.set_rules_hint(True)
        t.set_tooltip_column(5)
        uiutil.mkviewcoltxt(t, 'No.', 0, calign=1.0)
        uiutil.mkviewcoltxt(t, 'Ser', 1, calign=0.0)
        uiutil.mkviewcoltxt(t, 'Rider', 2, expand=True)
        uiutil.mkviewcoltxt(t, 'Org', 3, cb=self._editcol_cb)
        uiutil.mkviewcoltxt(t, 'Note', 4, width=80, cb=self._editcol_cb)
        t.show()
        t.connect('button_press_event', self._view_button_press)
        self._rlv = t
        b.get_object('riders_box').add(t)

        # create an event view
        self._elm = Gtk.ListStore(
            str,  # event id
            str,  # info
            str,  # type
            object,  # data ref
        )
        t = Gtk.TreeView(self._elm)
        #t.set_reorderable(True)
        t.set_rules_hint(True)
        t.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        uiutil.mkviewcoltxt(t, 'No.', 0)
        uiutil.mkviewcoltxt(t, 'Info', 1, expand=True, maxwidth=100)
        uiutil.mkviewcoltxt(t, 'Type', 2)
        t.show()
        t.connect('button_press_event', self._event_button_press)
        self._elv = t
        b.get_object('events_box').add(t)

        # get rider db
        _log.debug('Add riderdb')
        self.rdb = riderdb.riderdb()
        self.rdb.set_notify(self._rcb)

        # get event db and pack into scrolled pane
        _log.debug('Add eventdb')
        self.edb = eventdb.eventdb()
        self.edb.set_notify(self._ecb)

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
                                    'trackmeet': {
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
                title='trackmeet: Error',
                subtext='Trackmeet was unable to open a meet folder.')
        sys.exit(-1)

    lf = metarace.lockpath(configpath)
    if lf is None:
        _log.error('Unable to lock meet config, already in use')
        if not os.isatty(sys.stdout.fileno()):
            uiutil.messagedlg(
                message='Meet folder is locked.',
                title='trackmeet: Locked',
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
