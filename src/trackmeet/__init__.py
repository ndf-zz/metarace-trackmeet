# SPDX-License-Identifier: MIT
"""Timing and data handling application wrapper for track events."""
__version__ = '1.13.4'

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
from metarace import riderdb
from metarace import strops
from metarace import report
from metarace import unt4
from metarace.telegraph import telegraph, _CONFIG_SCHEMA as _TG_SCHEMA
from metarace.export import mirror, _CONFIG_SCHEMA as _EXPORT_SCHEMA
from metarace.timy import timy, _TIMER_LOG_LEVEL, _CONFIG_SCHEMA as _TIMY_SCHEMA
from metarace.comet import _CONFIG_SCHEMA as _COMET_SCHEMA
from .sender import sender, OVERLAY_CLOCK, _CONFIG_SCHEMA as _SENDER_SCHEMA
from .gemini import gemini
from .eventdb import eventdb, sub_autospec, sub_depend, event_type, _CONFIG_SCHEMA as _EVENT_SCHEMA
from . import uiutil
from . import scbwin
from . import race
from . import ps
from . import f200
from . import ittt
from . import sprnd
from . import classification
from . import aggregate

PRGNAME = 'org.6_v.trackmeet'
APPNAME = 'Trackmeet'
LOGFILE = 'event.log'
LOGFILE_LEVEL = logging.DEBUG
CONFIGFILE = 'config.json'
TRACKMEET_ID = 'trackmeet-2.0'  # configuration versioning
EXPORTPATH = 'export'
MAXREP = 10000  # communique max number
SESSBREAKTHRESH = 0.075  # forced page break threshold
ANNOUNCE_LINELEN = 80  # length of lines on text-only DHI announcer
MAX_AUTORECURSE = 8  # maximum levels of autostart dependency
RECOVER_TIMEOUT = 8  # ignore previous impulses that are too old

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
    'riderlist': {
        'prompt': 'Rider List:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Include?',
        'hint': 'Include list of riders on program of events',
        'attr': 'riderlist',
        'default': False,
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
    'domestic': {
        'prompt': 'Rules:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Domestic?',
        'hint': 'Apply domestic rule alterations to event defaults',
        'attr': 'domestic',
        'default': True,
    },
    'wsauth': {
        'prompt': 'UCI WS:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Enable?',
        'hint': 'Enable lookup of information via UCI web services',
        'attr': 'wsauth',
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
    'indexlink': {
        'prompt': 'Index link:',
        'hint': 'Meet-level link to parent folder',
        'attr': 'indexlink',
        'default': '../',
    },
    'prevlink': {
        'prompt': 'Previous link:',
        'hint': 'Meet-level link to previous on index of events',
        'attr': 'prevlink',
    },
    'nextlink': {
        'prompt': 'Next link:',
        'hint': 'Meet-level link to next on index of events',
        'attr': 'nextlink',
    },
    # deprecated config elements
    'linkbase': {
        'attr': 'linkbase',
        'control': 'none',
        'default': '.',
    },
}


def mkrace(meet, event, ui=True):
    """Create a new object of the correct type."""
    ret = None
    etype = event['type']
    if etype in (
            'indiv tt',
            'indiv pursuit',
            'pursuit race',
            'team sprint',
            'team sprint race',
            'team pursuit',
            'team pursuit race',
    ):
        ret = ittt.ittt(meet=meet, event=event, ui=ui)
    elif etype in (
            # 'scratch',  # requires some work
            'points',
            'madison',
            'omnium',
            'tempo',
            'progressive',
    ):
        ret = ps.ps(meet=meet, event=event, ui=ui)
    elif etype == 'classification':
        ret = classification.classification(meet=meet, event=event, ui=ui)
    elif etype in (
            'flying 200',
            'flying lap',
    ):
        ret = f200.f200(meet=meet, event=event, ui=ui)
    elif etype in (
            'sprint round',
            'sprint final',
    ):
        ret = sprnd.sprnd(meet=meet, event=event, ui=ui)
    ##elif etype == 'hour':
    ##ret = hourrec.hourrec(meet=meet, event=event, ui=ui)
    elif etype == 'team aggregate':
        ret = aggregate.teamagg(meet=meet, event=event, ui=ui)
    elif etype == 'indiv aggregate':
        ret = aggregate.indivagg(meet=meet, event=event, ui=ui)
    else:
        ret = race.race(meet=meet, event=event, ui=ui)
    return ret


class trackmeet:
    """Track meet application class."""

    ## Meet Menu Callbacks
    def get_event(self, evno, ui=False):
        """Return an event object for the given event number."""
        ret = None
        if evno in self.edb:
            eh = self.edb[evno]
            ret = mkrace(meet=self, event=eh, ui=ui)
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
        metarace.sysconf.add_section('comet', _COMET_SCHEMA)
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
                                        'comet': {
                                            'title': 'Comet',
                                            'schema': _COMET_SCHEMA,
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
                     exportfile=None,
                     template=None):
        """Print the supplied sections in a standard report."""
        _log.info('Printing report %s %s', subtitle, docstr)
        self.check_export_path()

        rep = report.report(template)
        rep.provisional = prov
        self.report_strings(rep)
        rep.strings['subtitle'] = (self.subtitle + ' ' + subtitle).strip()
        rep.strings['docstr'] = docstr
        for sec in sections:
            rep.add_section(sec)

        # write out to files if exportfile set
        if exportfile:
            rep.canonical = os.path.join(self.linkbase, exportfile + '.json')
            ofile = os.path.join(EXPORTPATH, exportfile + '.pdf')
            with metarace.savefile(ofile, mode='b') as f:
                rep.output_pdf(f)
            ofile = os.path.join(EXPORTPATH, exportfile + '.xlsx')
            with metarace.savefile(ofile, mode='b') as f:
                rep.output_xlsx(f)
            ofile = os.path.join(EXPORTPATH, exportfile + '.json')
            with metarace.savefile(ofile) as f:
                rep.output_json(f)
            lb = ''
            lt = []
            if self.mirrorpath:
                lb = os.path.join(self.linkbase, exportfile)
                lt = ['pdf', 'xlsx']
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

    def getrefid(self, refid):
        """Return a handle to the rider with the suplied refid or None."""
        ret = None
        refid = refid.lower()
        if refid in self._tagmap:
            ret = self.rdb[self._tagmap[refid]]
        elif 'riderno:' in refid:
            rno, rser = strops.bibstr2bibser(refid.split(':')[-1])
            ret = self.rdb.get_rider(rno, rser)
        return ret

    ## Event action callbacks
    def eventdb_cb(self, evlist, reptype=None):
        """Make a report containing start lists for the events listed."""
        # Note: selections via event listing override extended properties
        #       even if the selection does not really make sense, this
        #       allows for creation of reports manually crafted.
        secs = []
        reptypestr = reptype.title()
        template = None
        lsess = None
        for eno in evlist:
            if self.curevent is not None and eno == self.curevent.evno:
                self.save_curevent()
            if eno in self.edb:
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
                    secs.extend(h.startlist_report(program=True))
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
                              exportfile='trackmeet_' + reptype,
                              template=template)
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
        label = menuitem.get_label()
        etype = None
        if label != 'Add new':
            etype = event_type(label)
            if data is not None:
                etype = data
        event = self.edb.add_empty(notify=False)
        if etype is not None:
            event.set_value('type', etype)
        self.eventcb(None)
        self.select_event(event)

        # Backup an existing config
        oldconf = self.event_configfile(event['evid'])
        if os.path.isfile(oldconf):
            # There is already a config file for this event id
            bakfile = oldconf + '.old'
            _log.debug('Existing config saved to %r', bakfile)
            os.rename(oldconf, bakfile)
        GLib.idle_add(self.event_popup_edit_cb)

    def menu_race_recover_activate_cb(self, menuitem, data=None):
        """Attempt to recover missed start impulse."""
        if self.curevent is not None:
            self.curevent.recover_start()

    def menu_race_info_activate_cb(self, menuitem, data=None):
        """Show race information on scoreboard."""
        if self.curevent is not None:
            self.scbwin = None
            eh = self.curevent.event
            if self.showevno and eh['type'] not in ['break', 'session']:
                self.scbwin = scbwin.scbclock(self.scb,
                                              'Event ' + eh.get_evno(),
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
                _log.info('No next event to open')
        else:
            eh = self.event_getselected()
            if eh is not None:
                self.open_event(eh)
                self.select_event(eh)
            else:
                _log.info('No next event to open')

    def select_rider(self, rider):
        """Select rider in view if possible"""
        for r in self._rlm:
            if r[4] == rider:
                self._rlv.set_cursor(r.path, None, False)
                break
        else:
            _log.debug('Unable to select rider %r: not in view', rider)
        return False

    def select_event(self, event):
        """Find matching event in view and set selection"""
        for e in self._elm:
            if e[3] == event['evid']:
                self._elv.set_cursor(e.path, None, False)
                break
        else:
            _log.debug('Unable to select event %r: not in view', event)
        return False

    def menu_race_prev_activate_cb(self, menuitem, data=None):
        """Open the previous event on the program."""
        if self.curevent is not None:
            ph = self.edb.getprevrow(self.curevent.event)
            if ph is not None:
                self.open_event(ph)
                self.select_event(ph)
            else:
                _log.info('No previous event to open')
        else:
            eh = self.event_getselected()
            if eh is not None:
                self.open_event(eh)
                self.select_event(eh)
            else:
                _log.info('No previous event to open')

    def menu_race_close_activate_cb(self, menuitem, data=None):
        """Close currently open event."""
        self.close_event()

    def menu_race_abort_activate_cb(self, menuitem, data=None):
        """Close currently open event without saving."""
        if self.curevent is not None:
            self.curevent.readonly = True
        self.close_event()

    def open_evno(self, evno):
        """Open provided event by number, if it exists"""
        if evno in self.edb:
            self.open_event(self.edb[evno])
        return False

    def open_event(self, eventhdl=None):
        """Open provided event handle."""
        if eventhdl is not None:
            self.close_event()
            newevent = mkrace(self, eventhdl)
            newevent.loadconfig()
            self.curevent = newevent
            self.race_box.add(self.curevent.frame)
            if self.curevent.evtype not in ('classification', 'break',
                                            'team aggregate',
                                            'indiv aggregate'):

                self.menu_race_recover.set_sensitive(True)
            self.menu_race_info.set_sensitive(True)
            self.menu_race_close.set_sensitive(True)
            self.menu_race_abort.set_sensitive(True)
            self.menu_race_startlist.set_sensitive(True)
            self.menu_race_result.set_sensitive(True)
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
        """Fetch a flat list of places from the autospec.

        If final not set, return standings from incomplete event
        """
        places = {}
        for egroup in autospec.split(';'):
            _log.debug('Autospec group: %r', egroup)
            specvec = egroup.split(':')
            if len(specvec) == 2:
                evno = specvec[0].strip()
                if evno not in self.autorecurse:
                    self.autorecurse.add(evno)
                    placeset = strops.placeset(specvec[1])
                    if evno in self.edb:
                        e = self.edb[evno]
                        h = mkrace(self, e, False)
                        h.loadconfig()
                        isFinal = h.standingstr() == 'Result'
                        if not final or isFinal:
                            for ri in h.result_gen():
                                if isinstance(ri[1],
                                              int) and ri[1] in placeset:
                                    rank = ri[1]
                                    if rank not in places:
                                        places[rank] = []
                                    places[rank].append(ri[0])
                        h = None
                    else:
                        _log.warning('Autospec event not found: %r', evno)
                    self.autorecurse.remove(evno)
                else:
                    _log.debug('Ignoring loop in auto placelist: %r', evno)
            else:
                _log.warning('Ignoring erroneous autospec group: %r', egroup)
        ## TODO: insert placeholders 'X' for missing ranks and return
        ##       entries for all ranks 1-max
        ret = ''
        for place in sorted(places):
            ret += ' ' + '-'.join(places[place])
        _log.debug('Place set: %r', ret)
        return ret

    def autostart_riders(self, race, autospec='', infocol=None, final=True):
        """Try to fetch the startlist from race result info."""
        # infocol allows selection of seeding value for subsequent ruonds
        # possible values:
        #                   1 -> rank (ps/omnium, pursuit)
        #                   2 -> time (sprint)
        #                   3 -> info (handicap)
        # TODO: cache result gens
        if len(self.autorecurse) > MAX_AUTORECURSE:
            _log.debug('Recursion limit exceeded %s=%s', race.event['evid'],
                       autospec)
            return
        for egroup in autospec.split(';'):
            _log.debug('Autospec group: %r', egroup)
            specvec = egroup.split(':')
            if len(specvec) == 2:
                evno = specvec[0].strip()
                if evno in self.edb:
                    if evno not in self.autorecurse:
                        self.autorecurse.add(evno)
                        placeset = strops.placeset(specvec[1])
                        e = self.edb[evno]
                        evplacemap = {}
                        _log.debug('Loading places from event %r', evno)
                        ## load the place set map rank -> [(rider,seed),..]
                        h = mkrace(self, e, False)
                        h.loadconfig()
                        # Source is finished or omnium and dest not class
                        if h.finished or (h.evtype == 'omnium'
                                          and race.evtype not in
                                          ('classification', 'team aggregate',
                                           'indiv aggregate')):
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
                                    evplacemap[rank].append((ri[0], seed))
                        else:
                            _log.debug('Event %r not final', evno)
                        h = None
                        # maintain ordering of autospec
                        for p in placeset:
                            if p in evplacemap:
                                for ri in evplacemap[p]:
                                    race.addrider(ri[0], ri[1])
                        self.autorecurse.remove(evno)
                    else:
                        _log.debug('Ignoring loop in auto startlist: %r', evno)
                else:
                    _log.debug('Missing event in auto startlist: %r', evno)
            else:
                _log.warning('Ignoring erroneous autospec group: %r', egroup)

    def close_event(self):
        """Close the currently opened race."""
        if self.curevent is not None:
            self.menu_race_properties.set_sensitive(False)
            self.menu_race_decisions.set_sensitive(False)
            self.menu_race_recover.set_sensitive(False)
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
            delevent.event.set_value('dirty', True)  # mark event exportable
            delevent.saveconfig()
            delevent = None

    ## Data menu callbacks.
    def menu_data_import_activate_cb(self, menuitem, data=None):
        """Re-load event and rider info from disk."""
        if not uiutil.questiondlg(
                window=self.window,
                title='Reload Data',
                question='Re-load event and rider data from disk?',
                subtext='Note: The current event will be closed.'):
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
            self.finalresult()
        except Exception as e:
            _log.error('%s writing result: %s', e.__class__.__name__, e)
            raise

    def finalresult(self):
        provisional = self.provisional  # may be overridden below
        sections = []
        lastsess = None
        for e in self.edb:
            if e['resu']:  # include in result
                r = mkrace(self, e, False)
                nsess = e['sess']
                if nsess != lastsess:
                    sections.append(
                        report.pagebreak(SESSBREAKTHRESH))  # force break
                lastsess = nsess
                if r.evtype in ['break', 'session']:
                    sec = report.section()
                    sec.heading = ' '.join([e['pref'], e['info']]).strip()
                    sec.subheading = '\t'.join((
                        strops.lapstring(e['laps']),
                        e['distance'],
                        e['phase'],
                    )).strip()
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

        filebase = 'result'
        self.print_report(sections,
                          'Results',
                          prov=provisional,
                          doprint=False,
                          exportfile=filebase.translate(strops.WEBFILE_UTRANS))

    def printprogram(self):
        self.check_export_path()
        template = metarace.PROGRAM_TEMPLATE
        r = report.report(template)
        subtitlestr = 'Program of Events'
        if self.subtitle:
            subtitlestr = self.subtitle + ' - ' + subtitlestr
        self.report_strings(r)
        r.strings['docstr'] = ''  # What should go here?
        r.strings['subtitle'] = subtitlestr
        r.set_provisional(self.provisional)

        # add rider listing
        if self.riderlist:
            seccount = 0
            for series in self.rdb.listseries():
                if not series.startswith('t'):
                    smeta = self.rdb.get_rider(series, 'series')
                    if smeta is not None:
                        secid = 'riders'
                        if series:
                            secid += series
                        sec = report.twocol_startlist(secid)
                        sec.nobreak = True
                        sec.heading = smeta['title']
                        sec.subheading = smeta['subtitle']
                        sec.footer = smeta['footer']
                        aux = []
                        count = 0
                        for rid in self.rdb.biblistfromseries(series):
                            nr = self.rdb.get_rider(rid)
                            if nr is not None:
                                rno = strops.bibstr_key(nr['no'])
                                aux.append((
                                    rno,
                                    count,
                                    nr,
                                ))
                            else:
                                _log.warning('Missing details for rider %s',
                                             rid)
                        if aux:
                            aux.sort()
                            for sr in aux:
                                rh = sr[2]
                                sec.lines.append(
                                    ('', rh['no'], rh.resname(),
                                     rh.primary_cat(), None, None))
                            r.add_section(sec)
                            seccount += 1
                    else:
                        _log.debug('Skipping series %r in rider listing',
                                   series)
            if seccount > 0:
                r.add_section(report.pagebreak(0.01))

        cursess = None
        for e in self.edb:
            if e['program']:  # include this event in program
                if e['session']:  # add harder break for new session
                    if cursess and cursess != e['sess']:
                        r.add_section(report.pagebreak(SESSBREAKTHRESH))
                    cursess = e['sess']
                h = mkrace(self, e, False)
                h.loadconfig()
                s = h.startlist_report(program=True)
                for sec in s:
                    r.add_section(sec)
                h = None

        filebase = 'program'
        r.canonical = os.path.join(self.linkbase, filebase + '.json')
        ofile = os.path.join(EXPORTPATH, filebase + '.pdf')
        with metarace.savefile(ofile, mode='b') as f:
            r.output_pdf(f, docover=True)
            _log.info('Exported pdf program to %r', ofile)
        ofile = os.path.join(EXPORTPATH, filebase + '.html')
        with metarace.savefile(ofile) as f:
            r.output_html(f)
        ofile = os.path.join(EXPORTPATH, filebase + '.xlsx')
        with metarace.savefile(ofile, mode='b') as f:
            r.output_xlsx(f)
        ofile = os.path.join(EXPORTPATH, filebase + '.json')
        with metarace.savefile(ofile) as f:
            r.output_json(f)

    def menu_data_program_activate_cb(self, menuitem, data=None):
        """Export race program."""
        try:
            self.printprogram()
        except Exception as e:
            _log.error('%s writing report: %s', e.__class__.__name__, e)
            raise

    def menu_data_update_activate_cb(self, menuitem, data=None):
        """Update event index"""
        try:
            self.updateindex()
        except Exception as e:
            _log.error('%s updating event index: %s', e.__class__.__name__, e)
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
        self.check_export_path()
        orep = report.report()
        self.report_strings(orep)
        orep.strings['docstr'] = ''
        orep.strings['subtitle'] = self.subtitle
        orep.set_provisional(self.provisional)
        orep.shortname = self.shortname
        if self.indexlink:
            orep.indexlink = self.indexlink
        if self.nextlink:
            orep.nextlink = self.nextlink
        if self.prevlink:
            orep.prevlink = self.prevlink
        if self.provisional:
            orep.reportstatus = 'provisional'
        else:
            orep.reportstatus = 'final'

        pfilebase = 'program'
        pfile = os.path.join(EXPORTPATH, pfilebase + '.pdf')
        rfilebase = 'result'
        rfile = os.path.join(EXPORTPATH, rfilebase + '.pdf')

        lt = []
        lb = None
        if os.path.exists(rfile):
            lt = ['pdf', 'xlsx']
            lb = os.path.join(self.linkbase, rfilebase)
        elif os.path.exists(pfile):
            lt = ['pdf', 'xlsx']
            lb = os.path.join(self.linkbase, pfilebase)
        rsec = report.event_index('resultindex')
        rsec.heading = 'Results'
        sec = report.event_index('eventindex')
        sec.heading = 'Index of Events'
        #sec.subheading = Date?
        for eh in self.edb:
            if eh['result'] and eh['type'] in (
                    'classification', 'team aggregate',
                    'indiv aggregate'):  # include in result?
                referno = eh['evid']
                linkfile = None
                if referno:
                    linkfile = 'event_' + str(referno).translate(
                        strops.WEBFILE_UTRANS)
                descr = ' '.join([eh['pref'], eh['info']]).strip()
                extra = None  # STATUS INFO -> progress?
                rsec.lines.append(['', None, descr, extra, linkfile, None])

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
                if eh['evov']:
                    evno = eh['evov'].strip()
                sec.lines.append([evno, None, descr, extra, linkfile, target])
        if rsec.lines:
            orep.add_section(rsec)
        if sec.lines:
            orep.add_section(sec)
        basename = 'index'
        orep.canonical = os.path.join(self.linkbase, basename + '.json')
        ofile = os.path.join(EXPORTPATH, basename + '.html')
        with metarace.savefile(ofile) as f:
            orep.output_html(f, linkbase=lb, linktypes=lt)
        jbase = basename + '.json'
        ofile = os.path.join(EXPORTPATH, jbase)
        with metarace.savefile(ofile) as f:
            orep.output_json(f)

        GLib.idle_add(self.mirror_start)

    def mirror_start(self, dirty=None):
        """Create a new mirror thread unless in progress."""
        if self.mirrorpath and self.mirror is None:
            self.check_export_path()
            self.mirror = mirror(localpath=os.path.join(EXPORTPATH, ''),
                                 remotepath=self.mirrorpath,
                                 mirrorcmd=self.mirrorcmd)
            self.mirror.start()
        return False  # for idle_add

    def menu_data_export_activate_cb(self, menuitem, data=None):
        """Export race data."""
        if not self.exportlock.acquire(False):
            _log.info('Export already in progress')
            return None
        try:
            if self.exporter is not None:
                if not self.exporter.is_alive():
                    _log.debug('Stale exporter handle removed')
                    self.exporter = None
                else:
                    _log.info('Export already in progress')
                return False

            self.exporter = threading.Thread(target=self.__run_data_export,
                                             name='export',
                                             daemon=True)
            self.exporter.start()
            _log.debug('Started export thread[%s]', self.exporter.native_id)
        except Exception as e:
            _log.error('%s starting export: %s', e.__class__.__name__, e)
        finally:
            self.exportlock.release()

    def check_depends_dirty(self, evno, checked=None):
        """Recursively determine event dependencies"""
        if checked is None:
            checks = set()
        else:
            checks = set(checked)
        checks.add(evno)

        if evno not in self.edb:
            _log.debug('Dependency %r not in event model', evno)
            return False
        ev = self.edb[evno]

        # scan dependencies
        for dev in ev['depe'].split():
            if ev['dirty']:
                break
            if dev not in checks:
                dep = self.check_depends_dirty(dev, checks)
                checks.add(dev)
                if dep:
                    ev.set_value('dirty', True)
                    _log.debug('Event %r dirty by dependency %r', evno, dev)

        return ev['dirty']

    def check_export_path(self):
        """Ensure export path exists"""
        if not os.path.exists(EXPORTPATH):
            os.mkdir(EXPORTPATH)
            _log.info('Created export path: %r', EXPORTPATH)

    def __run_data_export(self):
        try:
            _log.debug('Begin data export')
            self.check_export_path()
            self.updatenexprev()  # re-compute next/prev link struct

            # determine 'dirty' events
            dmap = {}
            for e in self.edb:
                evno = e['evid']
                dirty = self.check_depends_dirty(evno)
                if dirty:
                    dmap[evno] = e
            dcnt = len(dmap)
            _log.debug('Marked %d event%s dirty', dcnt, strops.plural(dcnt))

            dirty = {}
            for evno, e in dmap.items():
                etype = e['type']
                series = e['series']
                evstr = (e['prefix'] + ' ' + e['info']).strip()
                doexport = e['result']
                e.set_value('dirty', False)
                _log.debug('Data export event %r', evno)
                r = mkrace(meet=self, event=e, ui=False)
                r.loadconfig()

                startrep = r.startlist_report()
                startsec = None

                if doexport:
                    orep = report.report()
                    orep.showcard = False
                    self.report_strings(orep)
                    orep.strings['subtitle'] = evstr
                    orep.strings['docstr'] = evstr
                    if etype in ('classification', 'team aggregate',
                                 'indiv aggregate'):
                        orep.strings['docstr'] += ' Classification'
                    orep.set_provisional(self.provisional)
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
                    orep.canonical = os.path.join(self.linkbase,
                                                  basename + '.json')
                    ofile = os.path.join(EXPORTPATH, basename + '.html')
                    with metarace.savefile(ofile) as f:
                        orep.output_html(f)
                    jbase = basename + '.json'
                    ofile = os.path.join(EXPORTPATH, jbase)
                    with metarace.savefile(ofile) as f:
                        orep.output_json(f)

                # release handle provided by mkrace
                r = None
            if self.mirrorpath:
                GLib.idle_add(self.mirror_start)
            _log.debug('End data export thread[%s]', self.exporter.native_id)
        except Exception as e:
            _log.error('%s data export: %s', e.__class__.__name__, e)
            raise

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
        uiutil.about_dlg(window=self.window, version=__version__)

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

        nt = tod.now().meridiem()
        if self.scb.connected():
            self.rfustat.update('ok', nt)
        else:
            self.rfustat.update('idle', nt)

        # check for completion in the export workers
        if self.mirror is not None:
            if not self.mirror.is_alive():
                _log.debug('Removing completed mirror')
                self.mirror = None

        if self.exporter is not None:
            if not self.exporter.is_alive():
                _log.debug('Removing completed export')
                self.exporter = None

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
    def recover_time(self, channel=None):
        """Recover (impulse, walltime) for the named channel if possible"""
        lt = self.main_timer.lastimpulse(channel)
        if lt is not None:
            # check for timeout
            nt = tod.now()
            if nt - lt[1] > RECOVER_TIMEOUT:
                lt = None
        if lt is not None:
            _log.debug('Recover %s %s @ %s',
                       strops.id2chan(strops.chan2id(channel)),
                       lt[0].rawtime(3), lt[1].meridiem())
        return lt

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

    def infoline(self, event):
        """Format event information for display on event info label."""
        evstr = event.get_info()
        if len(evstr) > 44:
            evstr = evstr[0:44] + '\u2026'
        return ('Event\u2006{}: {} [{}]'.format(event.get_evno(), evstr,
                                                event.get_type()))

    def racenamecat(self, event, slen=None, tail='', halign='c'):
        """Concatentate race info for display on scoreboard header line."""
        if slen is None:
            slen = self.scb.linelen
        evno = ''
        srcev = event.get_evno()
        if self.showevno and event['type'] != 'break':
            srcno = strops.posint(srcev, None)
            if srcno is not None:
                evno = 'Ev ' + srcev
        info = event['info']
        prefix = event['pref']
        ret = ' '.join((evno, prefix, info, tail)).strip()
        if len(ret) > slen + 1:
            ret = ' '.join((evno, info, tail)).strip()
            if len(ret) > slen + 1:
                ret = ' '.join((evno, tail)).strip()
        return strops.truncpad(ret, slen, align=halign)

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
        self.window.set_title('Trackmeet: ' +
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
        self.announce.exit(msg)
        self.scb.exit(msg)
        self.gemini.exit(msg)
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

    def _timercb(self, evt, data=None):
        _log.debug('Timer: %r %r', evt, data)
        if self.curevent is not None:
            GLib.idle_add(self.curevent.timercb,
                          evt,
                          priority=GLib.PRIORITY_HIGH)

    def _controlcb(self, topic=None, message=None):
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
        if self.curevent is not None:
            conf = self.event_configfile(self.curevent.event['evid'])
            backup = conf + '.1'
            try:
                if os.path.isfile(backup):
                    os.remove(backup)
                if os.path.isfile(conf):
                    _log.debug('Backup config %r to %r', conf, backup)
                    os.link(conf, backup)
            except Exception as e:
                _log.debug('Backup of %r to %r failed: %s', conf, backup, e)
            self.curevent.saveconfig()
            self.curevent.event.set_value('dirty', True)

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
            cw.set('trackmeet', 'curevent', self.curevent.evno)
            self.save_curevent()
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

        # Is this meet path an existing roadmeet?
        if cr.has_section('roadmeet'):
            _log.error('Meet folder contains road meet configuration')
            if not os.isatty(sys.stdout.fileno()):
                uiutil.messagedlg(
                    message='Invalid meet type.',
                    title='Trackmeet: Error',
                    subtext=
                    'Selected meet folder contains configuration for a road meet.'
                )
            sys.exit(-1)

        # Load schema options into meet object
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
        self.check_export_path()

        # re-open current event
        cureventno = cr.get('trackmeet', 'curevent')
        if cureventno and cureventno in self.edb:
            self.open_event(self.edb[cureventno])

        # check and warn of config mismatch
        cid = cr.get_value('trackmeet', 'id')
        if cid is not None and cid != TRACKMEET_ID:
            _log.warning('Meet config mismatch: %r != %r', cid, TRACKMEET_ID)

    def menu_import_chipfile_activate_cb(self, menuitem, data=None):
        """Import a transponder chipfile."""
        sfile = uiutil.chooseCsvFile(title='Select chipfile to import',
                                     parent=self.window,
                                     path='.')
        if sfile is not None:
            try:
                count = self.rdb.load_chipfile(sfile)
                _log.info('Imported %d refids from chipfile %s', count, sfile)
            except Exception as e:
                _log.error('%s importing chipfile: %s', e.__class__.__name__,
                           e)
        else:
            _log.debug('Import chipfile cancelled')

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
            oldId = self._cur_rider_sel
            dbr = self.rdb[oldId]
            wasDupe = False
            if oldId != dbr.get_id():
                _log.debug('Editing duplicate %r stored as %r', dbr.get_id(),
                           oldId)
                wasDupe = True
            schema = dbr.get_schema()
            label = dbr.get_label()
            short = 'Edit %s %s' % (label, dbr.get_bibstr())
            res = uiutil.options_dlg(window=self.window,
                                     title=short,
                                     action=True,
                                     sections={
                                         'rdb': {
                                             'title': label,
                                             'schema': schema,
                                             'object': dbr,
                                         },
                                     })
            if res['action'] == 0:  # OK
                if res['rdb']['no'][0] or res['rdb']['series'][0]:
                    # Change of number or series
                    self._cur_rider_sel = None  # selected row will be removed
                    backupDbr = None  # save a backup in case rider no exists
                    restoreDbr = None  # restore duplicate if primary avail
                    restoreIdx = None
                    newId = dbr.get_id()

                    # If curevent open and series matches old or new, close it
                    wasOpen = None
                    if self.curevent is not None:
                        if self.curevent.series in res['rdb']['series'][1:3]:
                            wasOpen = self.curevent.evno
                            self.close_event()

                    # Check for an existing entry with new ID
                    delDest = False  # delete dst from events before adding src
                    if newId in self.rdb:
                        backupDbr = self.rdb[newId]
                        self.rdb.del_rider(newId, notify=False)
                        _log.debug(
                            'New ID %r exists, flag removal of duplicate',
                            newId)
                        delDest = True

                    # Check for restore of duplicate back to original
                    moveSrc = True  # replace src in events with dst
                    if not wasDupe:
                        # Is there another entry in the rdb with this id?
                        for idx, r in self.rdb.items():
                            chkId = r.get_id()
                            # unless entry is self
                            # Note: not wasDupe implies oldId == dbr.get_id()
                            if idx != oldId and chkId == oldId:
                                # Yes, restore backup, leave id in meet
                                # Note: No need to notify, events are closed
                                #       name will be updated on reload
                                moveSrc = False
                                restoreDbr = r
                                restoreIdx = idx  # index != id in this case
                                break

                    # Remove oldId from index
                    self.rdb.del_rider(oldId, notify=False)

                    # Add modified rider back into index
                    self.rdb.add_rider(dbr, notify=False, overwrite=False)

                    # Restore duplicate if oldId was freed up
                    if restoreDbr is not None:
                        _log.debug('Restore backup %s %s %r',
                                   restoreDbr.get_label(),
                                   restoreDbr.get_bibstr(), restoreIdx)
                        self.rdb.del_rider(restoreIdx, notify=False)
                        self.rdb.add_rider(restoreDbr,
                                           notify=False,
                                           overwrite=False)

                    # Convert backup rider into a new duplicate entry
                    if backupDbr is not None:
                        _log.debug('Save copy of duplicate rider: %s',
                                   backupDbr.get_id())
                        self.rdb.add_rider(backupDbr,
                                           notify=False,
                                           overwrite=False)

                    # Visit all events and make required changes
                    oldSeries = res['rdb']['series'][1]
                    newSeries = res['rdb']['series'][2]
                    oldNo = res['rdb']['no'][1]
                    newNo = res['rdb']['no'][2]
                    if oldNo == newNo:
                        _log.debug('%s number unchanged', dbr.get_label())
                        moveSrc = False
                    _log.debug(
                        'Conditions: old=%s.%s, new=%s.%s, wasDupe=%r, delDest=%r, backupDbr=%r, moveSrc=%r, restoreDbr=%r, oldId=%r, newId=%r',
                        oldNo, oldSeries, newNo, newSeries, wasDupe, delDest,
                        backupDbr, moveSrc, restoreDbr, oldId, newId)
                    for ev in self.edb:
                        if ev['series'] in (oldSeries, newSeries):
                            _log.debug('Checking event %s series=%r',
                                       ev['evid'], ev['series'])
                            r = mkrace(meet=self, event=ev, ui=False)
                            r.readonly = False
                            r.loadconfig()
                            changed = False
                            oldIn = r.inevent(oldNo)
                            newIn = oldIn
                            if oldNo != newNo:
                                newIn = r.inevent(newNo)
                            _log.debug('oldIn=%r, newIn=%r', oldIn, newIn)
                            if oldIn or newIn:
                                if delDest:
                                    if newIn:
                                        _log.debug(
                                            'Remove stale %s from event %s',
                                            newNo, r.evno)
                                        r.delrider(newNo)
                                        changed = True
                                # altered rider number needs to be changed
                                if oldIn:
                                    if moveSrc:
                                        if r.changerider(oldNo, newNo):
                                            _log.debug(
                                                'Change %s -> %s event %s',
                                                oldNo, newNo, r.evno)
                                            changed = True
                                    else:
                                        _log.debug('Restore %s event %s',
                                                   oldNo, r.evno)
                                        r.addrider(newNo)
                                        _log.debug('Add %s event %s', newNo,
                                                   r.evno)
                                        changed = True

                                # mark event dirty
                                ev.set_value('dirty', True)
                            if changed:
                                r.saveconfig()
                            r = None
                        else:
                            _log.debug('Event %s not in series', ev['evid'])

                    # Notify without idling
                    self.ridercb(None)

                    # Try to select the modified row
                    GLib.idle_add(self.select_rider,
                                  newId,
                                  priority=GLib.PRIORITY_LOW)

                    # Re-open curevent if closed
                    if wasOpen is not None:
                        GLib.idle_add(self.open_evno, wasOpen),
                else:
                    for k in res['rdb']:
                        if res['rdb'][k][0]:
                            # there were non id/series changes
                            if not wasDupe:
                                # mark in-series events dirty
                                _log.debug('Marking series %s events dirty',
                                           dbr['series'])
                                for e in self.edb:
                                    if e['series'] == dbr['series']:
                                        e.set_value('dirty', True)
                            else:
                                _log.debug(
                                    'Edited %s %s was dupe, events not dirty',
                                    dbr.get_label(), dbr.get_bibstr())
                            self._rcb(oldId)
                            break
                    else:
                        _log.debug('No change to %s %s', dbr.get_label(),
                                   dbr.get_bibstr())

                # trigger export of dirty events
                self.delayed_export()

    def rider_lookup_cb(self, menuitem, data=None):
        _log.info('Rider lookup not yet enabled')

    def _editname_cb(self, cell, path, new_text, col):
        """Edit the rider name if possible."""
        old_text = self._rlm[path][1]
        if old_text != new_text:
            self._rlm[path][1] = new_text
            rId = self._rlm[path][4]
            dbr = self.rdb[rId]
            _log.debug('Updating %s %s detail', dbr.get_label(), dbr.get_id())
            dbr.rename(new_text)

    def delrider_events(self, riderNo, series):
        """Remove riderNo.series from all events on program"""
        for ev in self.edb:
            if ev['series'] == series:
                if ev['type'] not in ('classification', 'team aggregate',
                                      'indiv aggregate'):
                    r = mkrace(meet=self, event=ev, ui=False)
                    r.readonly = False
                    r.loadconfig()
                    if r.inevent(riderNo):
                        _log.debug('Remove %s from event %s', riderNo,
                                   ev['evid'])
                        r.delrider(riderNo)
                        r.saveconfig()
                        ev.set_value('dirty', True)
                    r = None

    def rider_delete_cb(self, menuitem, data=None):
        """Delete currently selected entry from meet"""
        if self._cur_rider_sel is not None and self._cur_rider_sel in self.rdb:
            selId = self._cur_rider_sel
            dbr = self.rdb[selId]
            series = dbr['series'].lower()
            wasDupe = False
            summary = dbr.summary()
            if selId != dbr.get_id():
                _log.debug('Removing duplicate %r stored as %r', dbr.get_id(),
                           selId)
                summary = 'Duplicate ' + summary
                wasDupe = True
            delId = dbr.get_id()
            riderNo = dbr['no']
            if uiutil.questiondlg(window=self.window,
                                  question='Delete %s from meet?' %
                                  (summary, ),
                                  title='Delete from Riderdb'):
                self._cur_rider_sel = None

                # If curevent open and series matches, close it
                wasOpen = None
                if self.curevent is not None:
                    if self.curevent.series == series:
                        wasOpen = self.curevent.evno
                        self.close_event()

                if wasDupe:
                    # Remove selection
                    self.rdb.del_rider(selId, notify=False)
                    _log.info('Duplicate %s %s removed', dbr.get_label(),
                              dbr.resname_bib())
                else:
                    # Is there another entry in the rdb with this id?
                    for idx, r in self.rdb.items():
                        chkId = r.get_id()
                        # unless entry is self
                        if idx != selId and chkId == selId:
                            # Yes, restore backup duplicate, leave id in meet
                            # Note: No need to notify since events are closed
                            #       name will be updated on reload
                            self.rdb.del_rider(selId, notify=False)
                            self.rdb.del_rider(idx, notify=False)
                            self.rdb.add_rider(r, notify=False)
                            GLib.idle_add(self.select_rider,
                                          chkId,
                                          priority=GLib.PRIORITY_LOW)
                            _log.info('Restored duplicate %s %s',
                                      r.get_label(), r.resname_bib())
                            break
                    else:
                        # Remove rider id from events with matching series
                        self.delrider_events(riderNo, series)
                        # Remove rider from index
                        self.rdb.del_rider(selId, notify=False)
                        _log.info('Removed %s %s from meet', dbr.get_label(),
                                  dbr.resname_bib())

                self.ridercb(None)
                if wasOpen is not None:
                    # re-open the new event after notification and reindex
                    GLib.idle_add(self.open_evno, wasOpen),

                # trigger export of dirty events
                self.delayed_export()
            else:
                _log.debug('Rider delete aborted')

    def rider_add_cb(self, menuitem=None, data=None):
        """Create a new rider entry and edit the content"""
        nser = ''
        dbr = None
        if menuitem is not None:
            nser = menuitem.get_label().lower().rsplit(maxsplit=1)[-1]
            if nser == 'copy':
                selId = self._cur_rider_sel
                if selId is not None and selId in self.rdb:
                    dbr = self.rdb[selId].copy()
                else:
                    _log.info('No rider selected, creating new record')
            elif nser == 'category':
                nser = 'cat'
            elif nser == 'add':
                nser = ''
            elif nser.startswith('t'):
                nser = 't'
        if dbr is None:
            # Create empty record of chosen type
            dbr = riderdb.rider(series=nser)
        schema = dbr.get_schema()
        rtype = schema['rtype']['prompt']
        short = 'Create New %s' % (rtype)
        res = uiutil.options_dlg(window=self.window,
                                 title=short,
                                 action=True,
                                 sections={
                                     'rdb': {
                                         'title': 'Rider',
                                         'schema': schema,
                                         'object': dbr,
                                     },
                                 })
        if res['action'] == 0:  # OK
            r = self.rdb.add_rider(dbr, overwrite=False, notify=False)
            # append row to view and select
            _log.info('Added %s %s', dbr.get_label(), dbr.resname_bib())
            self.ridercb(r)
            GLib.idle_add(self.select_rider, r, priority=GLib.PRIORITY_LOW)
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
            if event in self.edb:
                # update single entry in list
                e = self.edb[event]
                for lr in self._elm:
                    if lr[3] == event:
                        eno = e.get_evno()
                        if eno == e['evid']:
                            eno = ''
                        lr[0] = eno
                        lr[1] = e.get_info()
                        lr[2] = e.get_type()
                        lr[3] = e['evid']
                        break
                else:
                    _log.debug('Notified event not found: %r', event)
            else:
                _log.debug('Notified event not in model: %r', event)
        else:
            self._elm.clear()
            for e in self.edb:
                eno = e.get_evno()
                if eno == e['evid']:
                    eno = ''
                elr = [eno, e.get_info(), e.get_type(), e['evid']]
                self._elm.append(elr)
            _log.debug('Re-load event view')
        if self.curevent is not None:
            self.curevent.eventcb(event)
        return False

    def ridercb(self, rider):
        """Handle a change in the rider model"""
        if rider is not None:
            r = self.rdb[rider]
            summary = r.summary()
            if r['series'] != 'cat':
                # update refid maps
                otag = None
                ntag = r['refid'].lower()
                if rider in self._maptag:
                    otag = self._maptag[rider]
                if otag != ntag:
                    if rider in self._maptag:
                        del (self._maptag[rider])
                    if otag in self._tagmap:
                        del (self._tagmap[otag])
                    if ntag:
                        self._maptag[rider] = ntag
                        self._tagmap[ntag] = rider
                    _log.debug('Updated tag map %r = %r', ntag, rider)
            style = 0
            if rider != r.get_id():
                summary = 'Duplicate ' + summary
                style = 2
            for lr in self._rlm:
                if lr[4] == rider:
                    lr[0] = r.get_bibstr()
                    lr[1] = r.listname()
                    lr[2] = r['note']
                    lr[3] = htlib.escape(summary)
                    lr[5] = style
                    break
            else:
                lr = [
                    r.get_bibstr(),
                    r.listname(), r['note'],
                    htlib.escape(summary), rider, style
                ]
                self._rlm.append(lr)
        else:
            # assume entire map has to be rebuilt
            _log.debug('Re-build rider view')
            self._rlm.clear()
            for r in self.rdb:
                dbr = self.rdb[r]
                summary = dbr.summary()
                if dbr['series'] != 'cat':
                    refid = dbr['refid'].lower()
                    if refid:
                        self._tagmap[refid] = r
                        self._maptag[r] = refid
                style = 0
                if r != dbr.get_id():
                    summary = 'Duplicate ' + summary
                    style = 2
                rlr = [
                    dbr.get_bibstr(),
                    dbr.listname(),
                    dbr['note'],
                    htlib.escape(summary),
                    r,
                    style,
                ]
                self._rlm.append(rlr)
        if self.curevent is not None:
            self.curevent.ridercb(rider)
        return False

    def _rcb(self, rider):
        GLib.idle_add(self.ridercb, rider)

    def _ecb(self, event):
        GLib.idle_add(self.eventcb, event)

    def _editnote_cb(self, cell, path, new_text, col):
        """Callback for editing a rider note"""
        new_text = new_text.strip()
        rId = self._rlm[path][4]
        dbr = self.rdb[rId]
        if new_text != dbr['note']:
            dbr.set_value('note', new_text)
            self._rcb(rId)

    def event_getselected(self):
        """Return event for the currently selected row, or None."""
        ref = None
        model, plist = self._elv.get_selection().get_selected_rows()
        if len(plist) > 0:
            evno = self._elm[plist[0]][3]
            if evno in self.edb:
                ref = self.edb[evno]
            else:
                _log.error('Event %r in view not found in model', evno)
        return ref

    def event_popup_edit_cb(self, menuitem=None, data=None):
        """Edit event extended attributes."""
        evno = None
        ref = None
        model, plist = self._elv.get_selection().get_selected_rows()
        if len(plist) > 0:
            evno = self._elm[plist[0]][3]
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
        if res['edb']['evid'][0]:
            # event number was changed
            oldevno = res['edb']['evid'][1]
            newevno = res['edb']['evid'][2]

            wasOpen = None
            if self.curevent is not None:
                wasOpen = self.curevent.evno
                if wasOpen == oldevno:
                    wasOpen = newevno
                self.close_event()

            if newevno in self.edb:
                tmpevno = newevno
                baseno = newevno.rsplit('.', 1)[0]
                count = 0
                while tmpevno in self.edb:
                    count += 1
                    tmpevno = '%s.%d' % (
                        baseno,
                        count,
                    )
                _log.info('Backup existing event %s to %s', newevno, tmpevno)
                self.eventno_change(oldevno=newevno,
                                    newevno=tmpevno,
                                    backup=True)
            _log.info('Update event %s to %s', oldevno, newevno)
            self.eventno_change(oldevno=oldevno, newevno=newevno, backup=False)

            # force event view re-index
            self.eventcb(None)

            if wasOpen is not None:
                # re-open the new event after notification and reindex
                GLib.idle_add(self.open_evno, wasOpen),
        elif res['edb']['seri'][0]:
            if self.curevent is not None and evno == self.curevent.evno:
                _log.debug('Series change for event %s, reloading', evno)
                self.close_event()  # will mark event dirty
                self._ecb(evno)
                GLib.idle_add(self.open_evno, evno)
            else:
                ref.set_value('dirty', True)
                self._ecb(evno)
        else:
            for k in res['edb']:
                if res['edb'][k][0]:
                    ref.set_value('dirty', True)
                    self._ecb(evno)
                    break
        return False

    def eventno_change(self, oldevno, newevno, backup=False):
        """Handle a request to change an event number

        If backup is True, update evov, result, index and program flags
        in destination event

        """
        # first update the event db and index
        self.edb.change_evno(oldevno=oldevno, newevno=newevno, notify=False)

        # move configuration to new filename
        oldconf = self.event_configfile(oldevno)
        if os.path.isfile(oldconf):
            newconf = self.event_configfile(newevno)
            _log.debug('Moved event config from %r to %r', oldconf, newconf)
            os.rename(oldconf, newconf)

        # scan events for references
        for ev in self.edb:
            if ev['evid'] != newevno:
                if ev['auto']:
                    ev.update_autospec(oldevno, newevno)
                if ev['depend']:
                    ev.update_depend(oldevno, newevno)
                if ev['reference'] == oldevno:
                    ev.set_value('reference', newevno)
                # update evno references in event configs
                if ev['type'] in ('classification', ):
                    # TODO: update via schema
                    # showevents: list of evnos to include with result export
                    #  - same as depends in edb
                    # placesrc: autospec places for result
                    #  - same as auto starters in edb
                    dosave = False
                    config = self.event_configfile(ev['evid'])
                    ecr = jsonconfig.config()
                    ecr.add_section('event')
                    ecr.load(config)
                    oldshow = ecr.get_value('event', 'showevents')
                    if oldshow:
                        newshow = sub_depend(oldshow, oldevno, newevno)
                        if newshow != oldshow:
                            ecr.set('event', 'showevents', newshow)
                            dosave = True
                    oldplac = ecr.get_value('event', 'placesrc')
                    if oldplac:
                        newplac = sub_autospec(oldplac, oldevno, newevno)
                        if newplac != oldplac:
                            ecr.set('event', 'placesrc', newplac)
                            dosave = True
                    if dosave:
                        with metarace.savefile(config) as f:
                            ecr.write(f)
                elif ev['type'] in ('indiv aggregate', 'team aggregate'):
                    # TODO: requires a method
                    _log.warning('change evno not supported on %r', ev['type'])
                    dosave = False
                    config = self.event_configfile(ev['evid'])
                    ecr = jsonconfig.config()
                    ecr.add_section('event')
                    ecr.load(config)
                    # check sources
                    pass
                    if dosave:
                        with metarace.savefile(config) as f:
                            ecr.write(f)
                elif ev['type'] in ('tempo', 'progressive', 'points', 'omnium',
                                    'madison'):
                    # TODO: update via schema
                    # sprintsource: { sid: autospec, ... }
                    #    - same as autospec
                    dosave = False
                    config = self.event_configfile(ev['evid'])
                    ecr = jsonconfig.config()
                    ecr.add_section('sprintsource')
                    ecr.load(config)
                    for sid in ecr.options('sprintsource'):
                        oldplac = ecr.get_value('sprintsource', sid)
                        if oldplac:
                            newplac = sub_autospec(oldplac, oldevno, newevno)
                            if newplac != oldplac:
                                ecr.set('sprintsource', sid, newplac)
                                dosave = True
                    if dosave:
                        with metarace.savefile(config) as f:
                            ecr.write(f)
        if backup:
            # update event fields for a backup
            ev = self.edb[newevno]
            for key in ('index', 'result', 'program'):
                ev.set_value(key, False)
            ev.set_value('evov', oldevno)
        else:
            # assume edits to evov provided by operator
            pass

    def event_popup_report_cb(self, menuitem, data=None):
        """Print event report."""
        # report type from menu item
        report = menuitem.get_label().lower()

        sel = self._elv.get_selection()
        cnt = sel.count_selected_rows()
        # check for one selected
        if cnt == 0:
            _log.debug('No rows selected for report')
            return False

        # convert model iters into a list of event numbers
        model, iters = sel.get_selected_rows()
        elist = [model[i][3] for i in iters]

        # queue callback in main loop
        GLib.idle_add(self.eventdb_cb, elist, report)

    def event_popup_starters_cb(self, menuitem, data=None):
        """Prompt user to add riders to selected events"""
        sel = self._elv.get_selection()
        cnt = sel.count_selected_rows()
        # check for one selected
        if cnt == 0:
            _log.debug('No rows selected for starters')
            return False

        # check action
        action = 'add'
        if menuitem is not None and menuitem.get_label() == 'Del Starters':
            action = 'del'

        # convert model iters into a list of event numbers
        model, iters = sel.get_selected_rows()
        elist = [model[i][3] for i in iters]
        cnt = len(elist)
        msgv = []
        if action == 'add':
            msgv.append('Add to')
        else:
            msgv.append('Remove from')
        if cnt == 1:
            if elist[0] in self.edb:
                evt = self.edb[elist[0]]
                msgv.append('Event')
                evno = evt['evid']
                msgv.append(evno)
                evov = evt.get_evno()
                if evov != evno:
                    msgv.append('(%s)' % (evov, ))
                ifstr = evt.get_info()
                if ifstr:
                    msgv.append(':')
                    msgv.append(ifstr)
        else:
            msgv.append('%d selected events' % (cnt, ))
        msg = ' '.join(msgv)

        sections = {
            'starters': {
                'object': None,
                'title': 'Edit Starters',
                'schema': {
                    'title': {
                        'control': 'section',
                        'prompt': msg,
                    },
                    'adds': {
                        'prompt': 'Starters:',
                        'hint': 'Rider no list, range or category code',
                    }
                }
            }
        }
        res = uiutil.options_dlg(window=self.window,
                                 action=True,
                                 title='Add Starters',
                                 sections=sections)
        if res['action'] == 0:  # OK
            adds = res['starters']['adds'][2]
            for evid in elist:
                if evid in self.edb:
                    ev = self.edb[evid]
                    series = ev['series']
                    slist = strops.riderlist_split(adds, self.rdb, series)
                    if ev['type'] not in ('classification', 'indiv aggregate',
                                          'team aggregate'):
                        _log.debug('%s %r %r to %s', action, adds, slist,
                                   ev['evid'])
                        if self.curevent is not None and self.curevent.evno == evid:
                            for rno in slist:
                                if action == 'add':
                                    self.curevent.addrider(rno)
                                else:
                                    self.curevent.delrider(rno)
                            self.curevent.event.set_value('dirty', True)
                        else:
                            r = mkrace(meet=self, event=ev, ui=False)
                            r.readonly = False
                            r.loadconfig()
                            for rno in slist:
                                if action == 'add':
                                    r.addrider(rno)
                                else:
                                    r.delrider(rno)
                            r.saveconfig()
                            r = None
                        ev.set_value('dirty', True)

    def event_popup_duplicate_cb(self, menuitem, data=None):
        """Duplicate selected event program entries"""
        sel = self._elv.get_selection()
        cnt = sel.count_selected_rows()
        # check for one selected
        if cnt == 0:
            _log.debug('No rows selected for duplication')
            return False

        # convert model iters into a list of event numbers
        model, iters = sel.get_selected_rows()
        elist = [model[i][3] for i in iters]
        msg = ''
        if cnt == 1:
            if elist[0] in self.edb:
                evt = self.edb[elist[0]]
                msgv = ['Duplicate event']
                evno = evt['evid']
                msgv.append(evno)
                evov = evt.get_evno()
                if evov != evno:
                    msgv.append('(%s)' % (evov, ))
                ifstr = evt.get_info()
                if ifstr:
                    msgv.append(':')
                    msgv.append(ifstr)
                msgv.append('?')
                msg = ' '.join(msgv)
        else:
            msg = 'Duplicate %d selected events?' % (cnt, )

        if uiutil.questiondlg(window=self.window,
                              title='Duplicate Events',
                              question=msg):
            dpe = None
            for evt in elist:
                if evt in self.edb:
                    dpe = self.edb[evt].copy()
                    self.edb.add_event(dpe)
            self.eventcb(None)
            if cnt == 1:
                self.select_event(dpe)
                GLib.idle_add(self.event_popup_edit_cb)
            _log.info('Duplicated  %d event%s', cnt, strops.plural(cnt))

    def event_popup_reset_cb(self, menuitem, data=None):
        """Reset selected events"""
        sel = self._elv.get_selection()
        cnt = sel.count_selected_rows()
        # check for one selected
        if cnt == 0:
            _log.debug('No rows selected for reset')
            return False

        # convert model iters into a list of event numbers
        model, iters = sel.get_selected_rows()
        elist = [model[i][3] for i in iters]
        msg = ''
        if cnt == 1:
            if elist[0] in self.edb:
                evt = self.edb[elist[0]]
                msgv = ['Reset event']
                evno = evt['evid']
                msgv.append(evno)
                evov = evt.get_evno()
                if evov != evno:
                    msgv.append('(%s)' % (evov, ))
                ifstr = evt.get_info()
                if ifstr:
                    msgv.append(':')
                    msgv.append(ifstr)
                msgv.append(' to idle?')
                msg = ' '.join(msgv)
        else:
            msg = 'Reset %d selected events to idle?' % (cnt, )

        if uiutil.questiondlg(window=self.window,
                              title='Reset Events',
                              question=msg):
            wasOpen = None
            for evt in elist:
                if evt in self.edb:
                    if self.curevent is not None and self.curevent.evno == evt:
                        wasOpen = self.curevent.evno
                        self.close_event()
                    # Backup config
                    conf = self.event_configfile(evt)
                    if os.path.isfile(conf):
                        bakfile = conf + '.old'
                        os.rename(conf, bakfile)
                    _log.debug('Reset event %r', evt)

            # Re-open curevent if closed
            if wasOpen is not None:
                GLib.idle_add(self.open_evno, wasOpen),

            _log.info('Reset %d event%s', cnt, strops.plural(cnt))

    def event_popup_delete_cb(self, menuitem, data=None):
        """Delete selected events"""
        sel = self._elv.get_selection()
        cnt = sel.count_selected_rows()
        # check for one selected
        if cnt == 0:
            _log.debug('No rows selected for delete')
            return False

        # convert model iters into a list of event numbers
        model, iters = sel.get_selected_rows()
        elist = [model[i][3] for i in iters]
        msg = ''
        if cnt == 1:
            if elist[0] in self.edb:
                evt = self.edb[elist[0]]
                msgv = ['Delete event']
                evno = evt['evid']
                msgv.append(evno)
                evov = evt.get_evno()
                if evov != evno:
                    msgv.append('(%s)' % (evov, ))
                ifstr = evt.get_info()
                if ifstr:
                    msgv.append(':')
                    msgv.append(ifstr)
                msgv.append(' from meet?')
                msg = ' '.join(msgv)
        else:
            msg = 'Delete %d selected events from meet?' % (cnt, )

        if uiutil.questiondlg(window=self.window,
                              title='Delete Events',
                              question=msg):
            for evt in elist:
                if evt in self.edb:
                    if self.curevent is not None and self.curevent.evno == evt:
                        self.close_event()
                    _log.debug('Deleting event %r', evt)
                    del self.edb[evt]
            self._ecb(None)
            _log.info('Deleted %d event%s', cnt, strops.plural(cnt))

    def _event_inserted(self, elv, path, i, data=None):
        """Handle reorder by dnd - first half"""
        if len(elv) > len(self.edb):
            self._eld = path.get_indices()
            _log.debug('DND Start: %s', path)

    def _event_deleted(self, elv, path, data=None):
        """Handle reorder by dnd - second half"""
        if self._eld and len(elv) == len(self.edb):
            _log.debug('DND Finish: %s, %r', path, self._eld)
            self._eld = None
            self.edb.reindex((e[3] for e in self._elm))

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

                        self._event_menu_copy.set_sensitive(True)
                        self._event_menu_reset.set_sensitive(True)
                        self._event_menu_del.set_sensitive(True)
                    else:
                        _log.error('Invalid selection ignored')
                        self._cur_rider_sel = None
                        self._event_menu_edit.set_sensitive(False)
                        self._event_menu_copy.set_sensitive(False)
                        self._event_menu_reset.set_sensitive(False)
                        self._event_menu_del.set_sensitive(False)
                else:
                    self._cur_rider_sel = None
                    self._event_menu_edit.set_sensitive(False)
                    self._event_menu_copy.set_sensitive(False)
                    self._event_menu_reset.set_sensitive(False)
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
                        self._cur_rider_sel = r[4]
                        self._rider_menu_edit.set_sensitive(True)
                        self._rider_menu_copy.set_sensitive(True)
                        if self.wsauth:
                            self._rider_menu_lookup.set_sensitive(True)
                        else:
                            self._rider_menu_lookup.set_sensitive(False)
                        self._rider_menu_del.set_sensitive(True)
                    else:
                        _log.error('Invalid selection ignored')
                        self._cur_rider_sel = None
                        self._rider_menu_edit.set_sensitive(False)
                        self._rider_menu_copy.set_sensitive(False)
                        self._rider_menu_lookup.set_sensitive(False)
                        self._rider_menu_del.set_sensitive(False)
                else:
                    self._cur_rider_sel = None
                    self._rider_menu_edit.set_sensitive(False)
                    self._rider_menu_copy.set_sensitive(False)
                    self._rider_menu_lookup.set_sensitive(False)
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
        self.domestic = True
        self.riderlist = False
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
        self.indexlink = '../'
        self.prevlink = None
        self.nextlink = None
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
        self.announce.setcb(self._controlcb)
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
        self.wsauth = False  # Enable UCI web services

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
        self.menu_race_recover = b.get_object('menu_race_recover')
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
        self._rider_menu_copy = b.get_object('rider_copy')
        self._rider_menu_lookup = b.get_object('rider_lookup')
        self._rider_menu_del = b.get_object('rider_del')
        self._cur_rider_sel = None
        self._event_menu = b.get_object('event_context')
        self._event_menu_edit = b.get_object('event_edit')
        self._event_menu_copy = b.get_object('event_copy')
        self._event_menu_reset = b.get_object('event_reset')
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
        self.sh.setLevel(_TIMER_LOG_LEVEL)  # show timer+ on status bar
        rootlogger.addHandler(self.sh)
        self.lh = uiutil.textViewHandler(self.log_buffer, self.log_view,
                                         self.log_scroll)
        self.lh.setFormatter(f)
        self.lh.setLevel(logging.INFO)  # show info+ in text view
        rootlogger.addHandler(self.lh)

        # Build a rider list store and view
        self._rlm = Gtk.ListStore(
            str,  # BIB.ser 0
            str,  # name 1
            str,  # note 2
            str,  # tooltip 3
            object,  # rider ref 4
            int,  # text variant 5
        )
        t = Gtk.TreeView(self._rlm)
        t.set_rules_hint(True)
        t.set_tooltip_column(3)
        uiutil.mkviewcoltxt(t, 'No.', 0, calign=1.0, style=5)
        uiutil.mkviewcoltxt(t,
                            'Rider',
                            1,
                            expand=True,
                            style=5,
                            cb=self._editname_cb)
        uiutil.mkviewcoltxt(t, '', 2, width=80, cb=self._editnote_cb)
        t.show()
        t.connect('button_press_event', self._view_button_press)
        self._rlv = t
        b.get_object('riders_box').add(t)

        # create an event view
        self._elm = Gtk.ListStore(
            str,  # event no
            str,  # info
            str,  # type
            str,  # event id
        )
        self._elm.connect('row-inserted', self._event_inserted)
        self._elm.connect('row-deleted', self._event_deleted)
        self._eld = None  # drag reordering flag
        t = Gtk.TreeView(self._elm)
        t.set_reorderable(True)
        t.set_rules_hint(True)
        t.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        uiutil.mkviewcoltxt(t, 'ID', 3)
        uiutil.mkviewcoltxt(t, 'No', 0)
        uiutil.mkviewcoltxt(t, 'Info', 1, expand=True, maxwidth=100)
        uiutil.mkviewcoltxt(t, 'Type', 2)
        t.show()
        t.connect('button_press_event', self._event_button_press)
        self._elv = t
        b.get_object('events_box').add(t)

        self._tagmap = {}
        self._maptag = {}

        # get rider db
        _log.debug('Add riderdb')
        self.rdb = riderdb.riderdb()
        self.rdb.set_notify(self._rcb)

        # get event db and pack into scrolled pane
        _log.debug('Add eventdb')
        self.edb = eventdb()
        self.edb.set_notify(self._ecb)

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
    metarace.sysconf.add_section('comet', _COMET_SCHEMA)
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
                                    'comet': {
                                        'title': 'Comet',
                                        'schema': _COMET_SCHEMA,
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


def loadmeet():
    """Select meet folder with chooser dialog"""
    return uiutil.chooseFolder(title='Open Meet Folder',
                               path=metarace.DATA_PATH)


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

    try:
        GLib.set_prgname(PRGNAME)
        GLib.set_application_name(APPNAME)
        Gtk.Window.set_default_icon_name(metarace.ICON)
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
        elif sys.argv[1] == '--create':
            configpath = createmeet()
        else:
            configpath = sys.argv[1]
    else:
        configpath = loadmeet()
    configpath = metarace.config_path(configpath)
    if configpath is None:
        _log.debug('Missing path, command: %r', sys.argv)
        _log.error('Error opening meet')
        if not os.isatty(sys.stdout.fileno()):
            uiutil.messagedlg(
                message='Error opening meet',
                title='Trackmeet: Error',
                subtext='Trackmeet was unable to open a meet folder')
        sys.exit(-1)

    lf = metarace.lockpath(configpath)
    if lf is None:
        _log.error('Unable to lock meet config, already in use')
        if not os.isatty(sys.stdout.fileno()):
            uiutil.messagedlg(
                message='Meet folder is locked',
                title='Trackmeet: Locked',
                subtext='Another application has locked the meet folder for use'
            )
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


if __name__ == '__main__':
    sys.exit(main())
