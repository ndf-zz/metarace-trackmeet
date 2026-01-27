# SPDX-License-Identifier: MIT
"""UCI Hour Record Handler - Minimal Version.

Notes on the interpretation of the standing rules, January 2026:

  3.5.011 Record attempts shall be electronically timed lap by lap to the nearest
          thousandth of a second.

     - This line is to be ignored, refer 3.2.015 instead, times should be truncated

  3.5.031 The distance covered in the hour shall be calculated as follows [...]

     - The "last complete lap" is the one in which the hour expires.

     - In the case that a rider arrives at their start line at the same
       instant the hour expires, the attempt is considered complete and
       that lap shall be considered the "last lap" used for TTC.
       DiC in this case will equal LPi since TTC will equal TRC.

"""

import gi
import logging
from math import floor

gi.require_version("GLib", "2.0")
from gi.repository import GLib

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

import metarace
from metarace import tod
from metarace import strops
from metarace import report
from metarace import jsonconfig

from . import uiutil
from . import scbwin

_log = logging.getLogger('hourrec')
_log.setLevel(logging.DEBUG)

# config version string
EVENT_ID = 'hourrec-1.0'

# scb function keys
_key_armstart = 'F5'
_key_reset = 'F5'
_key_timer = 'F6'

# internal constants
_DURATION = tod.HOUR
_MINLAP = tod.mktod('14.0')
_MAXAVG = tod.mktod(120)
_PROJLAP = 12
_MINPROJ = 30000
_MAXPROJ = 60000
_PESSIMISM = 0.99  # Assume 1% slowdown in predictions
_CHAN_START = 0
_CHAN_MAN = 1
_CHAN_LAP = 2
_CHAN_HALF = 3

_CONFIG_SCHEMA = {
    'etype': {
        'prompt': 'UCI Hour Record',
        'control': 'section',
    },
    'rider': {
        'prompt': 'Rider:',
        'control': 'short',
        'hint': 'Competitor rider number',
        'default': None,
    },
    'reclen': {
        'prompt': 'Duration:',
        'hint': 'Record duration',
        'type': 'tod',
        'control': 'short',
        'places': 0,
        'attr': '_reclen',
        'default': _DURATION,
    },
    'minlap': {
        'prompt': 'Min Lap:',
        'hint': 'Minimum allowed lap time',
        'type': 'tod',
        'places': 1,
        'control': 'short',
        'attr': '_minlap',
        'default': _MINLAP,
    },
    'wallstart': {
        'prompt': 'Start:',
        'hint': 'Scheduled attempt start time',
        'type': 'tod',
        'places': 0,
        'control': 'short',
        'attr': '_wallstart',
        'default': None,
    },
    'record': {
        'prompt': 'Record:',
        'hint': 'Current record distance to beat',
        'type': 'int',
        'attr': '_record',
        'control': 'short',
        'subtext': '(metres)',
        'default': None,
    },
    'target': {
        'prompt': 'Target:',
        'hint': "Rider's desired target distance",
        'type': 'int',
        'attr': '_target',
        'control': 'short',
        'subtext': '(metres)',
        'default': None,
    },
    'projlap': {
        'prompt': 'Project Lap:',
        'hint': 'Start distance projections after this lap',
        'type': 'int',
        'attr': '_projlap',
        'control': 'short',
        'default': _PROJLAP,
    },
    'minproj': {
        'prompt': 'Min projection:',
        'hint': 'Minimum reported projected distance',
        'type': 'int',
        'attr': '_minproj',
        'control': 'short',
        'subtext': '(metres)',
        'default': _MINPROJ,
    },
    'maxproj': {
        'prompt': 'Max projection:',
        'hint': 'Maximum reported projected distance',
        'type': 'int',
        'attr': '_maxproj',
        'control': 'short',
        'subtext': '(metres)',
        'default': _MAXPROJ,
    },
}

_TIMING_SCHEMA = {
    'start': {
        'prompt': 'Start Time:',
        'control': 'short',
        'type': 'tod',
        'hint': 'Chronometer start time',
        'attr': '_start',
        'places': 4,
        'default': None,
        'readonly': True,
    },
    'lstart': {
        'prompt': 'Local Start:',
        'control': 'short',
        'type': 'tod',
        'hint': 'Host computer start time',
        'attr': '_lstart',
        'places': 4,
        'default': None,
        'readonly': True,
    },
    'finish': {
        'prompt': 'Finish:',
        'control': 'short',
        'type': 'tod',
        'hint': 'Chronometer finish time',
        'places': 4,
        'attr': '_finish',
        'default': None,
        'readonly': True,
    },
    'lapcount': {
        'prompt': 'Lap count:',
        'control': 'short',
        'type': 'int',
        'hint': 'Count of completed laps',
        'attr': '_lapcount',
        'default': 0,
    },
    'mancount': {
        'prompt': 'Man count:',
        'control': 'short',
        'type': 'int',
        'hint': 'Manual/backup lap counter',
        'attr': '_mancount',
        'default': 0,
    },
    'lastlap': {
        'prompt': 'Final lap:',
        'control': 'short',
        'type': 'tod',
        'hint': 'Lap time in which the hour expired',
        'places': 3,
        'attr': '_lastlap',
        'default': None,
        'readonly': True,
    },
}


class UCIHour:
    """Handler for the UCI Hour Record."""

    def force_running(self, start=None):
        """Set event start and update current."""
        self.meet.set_event_start(self.event)
        self.resend_current()

    def show_lapscore(self, laps, prev):
        """Respond to changes in facility lapscore, return True if accepted."""
        ret = False
        if prev is not None and laps is not None:
            if self._start is not None:
                if laps - prev == 1:  # only announce increment of laps for hour
                    ret = True
        return ret

    def ridercb(self, rider):
        """Rider (no, series) change notification callback."""
        if self.winopen and self._rider is not None:
            if rider is not None:
                series = rider[1]
                if series == self.series:
                    rno = rider[0]
                    if rno == self._rider['no']:
                        self._updateRider()
            else:
                self._updateRider()

    def _riderName(self):
        nv = []
        if self._rider is not None:
            nv.append(self._rider.fitname(48))
            if self._rider['nationality']:
                nv.append('(%s)' % (self._rider['nationality'], ))
            for field in ('class', 'categories', 'uciid'):
                if self._rider[field]:
                    nv.append(self._rider[field])
        return ' '.join(nv)

    def _updateRider(self):
        """Update displayed rider information."""
        if self._rider is not None:
            self._timer.bibent.set_text(self._rider['no'])
            self._timer.biblbl.set_text(self._riderName())
        else:
            _log.debug('Competitor information not set')
            self._timer.toidle()
        self.resend_current()

    def eventcb(self, event):
        """Event change notification callback."""
        if self.winopen:
            if event is None or event == self.evno:
                if self.prefix_ent.get_text() != self.event['pref']:
                    self.prefix_ent.set_text(self.event['pref'])
                if self.info_ent.get_text() != self.event['info']:
                    self.info_ent.set_text(self.event['info'])
                self.update_expander_lbl_cb()

    def changerider(self, oldNo, newNo):
        """Update rider no in event"""
        oldNo = oldNo.upper()
        newNo = newNo.upper()
        if self.inevent(oldNo):
            if oldNo != newNo and not self.inevent(newNo):
                self._rider = self.meet.rdb.get_rider(newNo, self.series)
                self._updateRider()
                return True
        return False

    def inevent(self, bib):
        """Return true if rider appears in model."""
        return self._rider is not None and self._rider['no'] == bib

    def addrider(self, bib='', info=None):
        """Add specified rider to race model."""
        if self._rider is None:
            self._rider = self.meet.rdb.get_rider(bib, self.series)
            if self._rider is None:
                _log.debug('Rider (%s,%s) not found, not added', bib, series)
            self._updateRider()
        else:
            _log.warning(
                'Rider %s not added: Competitor already set, remove %s first',
                bib, self._rider['no'])

    def delrider(self, bib):
        """Remove the specified rider from the model."""
        bib = bib.upper()
        if self._rider is not None and self._rider['no'] == bib:
            self._rider = None
            _log.debug('Removed rider %s', bib)
            self._updateRider()
        else:
            _log.debug('Rider %s not in event', bib)

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        if self.winopen:
            # clear page
            self.meet.txt_clear()
            self.meet.txt_title(self.event.get_info(showevno=True))
            self.meet.txt_line(1)
            ##! TODO - annouce
            self.resend_current()
        return False

    def loadconfig(self):
        """Load race config from disk."""
        self.onestart = False
        self.finished = False
        self._tracelog.clear()
        self._splitlist.clear()

        cr = jsonconfig.config({
            'event': {
                'id': EVENT_ID,
                'showinfo': False,
                'decisions': [],
            },
        })
        cr.add_section('event', _CONFIG_SCHEMA)
        cr.add_section('timing', _TIMING_SCHEMA)
        if not cr.load(self.configfile):
            _log.info('%r not read, loading defaults', self.configfile)

        self.decisions = cr.get('event', 'decisions')
        cr.export_section('event', self)  # pull in config from schema
        cr.export_section('timing', self)  # pull in timing from schema

        # read in 'special' runtime values
        rno = cr.get_value('event', 'rider')
        self._rider = self.meet.rdb.get_rider(rno, self.series)
        self._weather = cr.get_value('timing', 'weather')
        trace = cr.get_value('timing', 'trace')
        if trace is not None and isinstance(trace, list):
            self._tracelog.extend(trace)
        splits = cr.get_value('timing', 'splitlist')
        if splits is not None and isinstance(splits, list):
            for st in splits:
                self._splitlist.append(tod.mktod(st))

        # reset event state flags
        if self._start is not None:
            self.onestart = True
            if self._finish is not None:
                self.finished = True
                self.timerstat = 'finished'
            else:
                self.timerstat = 'running'

        # update ui and re-join timer if required
        if self.winopen:
            self.update_expander_lbl_cb()
            self.info_expand.set_expanded(
                strops.confopt_bool(cr.get('event', 'showinfo')))
            self._updateRider()

            if self._start is not None:
                _log.debug('Re-join event in progress')
                self._timer.start(self._start)
                if self._finish is not None:
                    _log.debug('Attempt finished')
                    self._timer.finish(self._finish)
                    self._endtrace()
                    self._disarmchrono()
                else:
                    _log.debug('Re-join event in progress')
                    self._starttrace()
                    self._armchrono()
            else:
                # should be idle on load already
                pass
            # bring up timer win after load
            GLib.idle_add(self.showtimerwin)
        else:
            self._winState['showinfo'] = cr.get('event', 'showinfo')

        self.recalculate()

        # After load complete - check config and report.
        eid = cr.get('event', 'id')
        if eid and eid != EVENT_ID:
            _log.info('Event config mismatch: %r != %r', eid, EVENT_ID)

    def saveconfig(self):
        """Save race to disk."""
        if self.readonly:
            _log.error('Attempt to save readonly event')
            return
        cw = jsonconfig.config()
        cw.add_section('event', _CONFIG_SCHEMA)
        cw.add_section('timing', _TIMING_SCHEMA)
        cw.import_section('event', self)
        cw.import_section('timing', self)
        if self._rider is not None:
            cw.set('event', 'rider', self._rider['no'])
        else:
            cw.set('event', 'rider', None)
        cw.set('timing', 'weather', self._weather)
        cw.set('timing', 'splitlist', self._splitlist)
        cw.set('timing', 'trace', self._tracelog)
        cw.set('event', 'id', EVENT_ID)
        _log.debug('Saving event config %r', self.configfile)
        with metarace.savefile(self.configfile) as f:
            cw.write(f)

    def startlist_report(self, program=False):
        """Return a startlist report."""
        ret = []
        sec = None
        etype = self.event['type']
        twocol = True
        rankcol = None
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)

        sec.nobreak = True
        headvec = self.event.get_info(showevno=True).split()
        if not program:
            headvec.append('Start List')
        else:
            rankcol = ' '
        sec.heading = ' '.join(headvec)
        # suppress "laps" string on hour reports
        substr = '\u3000'.join(
            (self.event['distance'], self.event['rules'])).strip()
        if substr:
            sec.subheading = substr

        self._startlines = []
        sec.lines = []
        cnt = 0
        if self._rider is not None:
            cnt = 1
            rno = ' '  # suppress rider no
            dbrno = self._rider['no']
            rnat = self._rider['nationality']
            rname = self._rider.resname()
            inf = self._rider['class']
            pilot = self.meet.rdb.get_pilot_line(self._rider)
            pname = None
            if pilot:
                pname = pilot[2]
            sec.lines.append([None, rno, rname, inf, None, None])
            if pilot:
                sec.lines.append(pilot)
            self._startlines.append({
                'competitor': dbrno,
                'nation': rnat,
                'name': rname,
                'info': inf,
                'pilot': pname,
            })

        # Prizemoney line
        sec.prizes = self.meet.prizeline(self.event)

        # Footer line
        sec.footer = self.meet.footerline(self.event, count=cnt)

        ret.append(sec)
        return ret

    def get_startlist(self):
        """Return a list of riders in the model."""
        if self._rider is not None:
            return self._rider['no']
        else:
            return ''

    def do_properties(self):
        """Run event properties dialog."""
        if self._rider is not None:
            _CONFIG_SCHEMA['rider']['value'] = self._rider['no']
        else:
            _CONFIG_SCHEMA['rider']['value'] = None
        res = uiutil.options_dlg(
            window=self.meet.window,
            title='Hour Record Properties',
            sections={
                'hour': {
                    'title': 'Event Config',
                    'schema': _CONFIG_SCHEMA,
                    'object': self,
                },
                'timing': {
                    'title': 'Timing',
                    'schema': _TIMING_SCHEMA,
                    'object': self,
                },
            },
            action=True,
        )
        if res['action'] == 0:  # OK
            if res['hour']['rider'][0]:
                newNo = res['hour']['rider'][2]
                self._rider = self.meet.rdb.get_rider(newNo, self.series)
                if self._rider is not None:
                    _log.debug('Updated rider: %s', self._rider.summary())
                else:
                    _log.debug('Cleared rider')
                self._updateRider()
                ##! recalculate
        else:
            _log.debug('Edit properties cancelled')
        return False

    def _armchrono(self):
        """Arm chronometer inputs."""
        self.meet.delayimp('0.01')
        self.meet.main_timer.armlock(True)
        self.meet.main_timer.arm(_CHAN_MAN)
        self.meet.main_timer.arm(_CHAN_LAP)
        self.meet.main_timer.arm(_CHAN_HALF)

    def _disarmchrono(self):
        """Disarm chronometer inputs."""
        self.meet.delayimp('2.00')
        for i in range(0, 8):
            self.meet.main_timer.dearm(i)
        self.meet.main_timer.armlock(False)

    def armstart(self):
        """Handle arm start request."""
        if self.timerstat == 'idle':
            self.toarmstart()
        elif self.timerstat == 'armstart':
            self.toidle()

    def toarmstart(self):
        """Arm for a start trigger."""
        self._starttrace()
        self._timer.toarmstart()
        self.timerstat = 'armstart'
        self.meet.main_timer.arm(_CHAN_START)
        self.meet.delayimp('0.01')  # adjust delay but don't armlock yet
        if self._rider is not None:
            self.meet.timer_log_msg(self._rider['no'],
                                    self._rider.fitname(width=20, trunc=True))
        self.meet.timer_log_env()

    def _starttrace(self):
        """Enable the trace log handler."""
        if self._trace is None:
            self._trace = uiutil.traceHandler(self._tracelog)
            logging.getLogger().addHandler(self._trace)

    def _endtrace(self):
        """Disable the trace log handler."""
        if self._trace is not None:
            logging.getLogger().removeHandler(self._trace)
            self._trace = None

    def torunning(self, st, walltime=None):
        """Set event to running state."""
        if walltime is not None:
            self._lstart = walltime
        else:
            self._lstart = tod.now()
        self._timer.start(st)
        self._start = st
        self.timerstat = 'running'
        self._status = 'virtual'
        self.onestart = True
        self._starttrace()
        if self._weather is None:
            self._weather = self.meet.get_weather()
        self._armchrono()
        self.meet.main_timer.dearm(_CHAN_START)
        _log.debug('Event started')

    def toidle(self):
        """Reset event to idle."""

        # disconnect trace logger
        self._endtrace()

        # idle timer
        self.timerstat = 'idle'
        self._status = None
        self._timer.toidle()
        self._updateRider()

        # disarm and unlock chronometer
        self._disarmchrono()

        # clear out all state
        self._start = None
        self._lstart = None
        self._finish = None
        self._weather = None
        self._lapcount = 0
        self._mancount = 0
        self._lastlap = None
        self._prevlap = None
        self._splitlist.clear()
        self._tracelog.clear()
        self.recalculate

        if self.winopen:
            self.showtimerwin()
        _log.info('Reset to idle')

    def showtimerwin(self):
        """Display running info on the scoreboard."""
        header = 'Something'
        subheader = 'Something ELse'
        self.meet.scbwin = scbwin.scbtt(scb=self.meet.scb,
                                        header=header,
                                        subheader=subheader)
        self._timerwin = True
        self._lelap = None
        self.meet.scbwin.reset()
        self.meet.db.setScoreboardHint('timing')
        self.resend_current()
        return False

    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == Gdk.EventType.KEY_PRESS:
            key = Gdk.keyval_name(event.keyval) or 'None'
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                if key == _key_reset:  # override ctrl+f5
                    self._abortcnt += 1
                    if self._abortcnt > 4:
                        self.toidle()
                        self._abortcnt = 0
                    elif self._abortcnt == 1:
                        _log.info('Press Ctrl+F5 five times to reset')
                    return True
            self._abortcnt = 0
            if key[0] == 'F':
                if key == _key_armstart:
                    self.armstart()
                    return True
                elif key == _key_timer:
                    self.showtimerwin()
                    return True
        return False

    def resend_current(self):
        fragment = self.event.get_fragment()
        if fragment:
            data = self.data_pack()
            self.meet.db.sendCurrent(self.event, fragment, data)

    def data_pack(self):
        """Pack standard values for a current object"""
        ret = {}
        ret['competitionType'] = 'hour'

        ret['status'] = self._status

        if self._weather is not None:
            ret['weather'] = self._weather
        if self._startlines is not None:
            ret['competitors'] = self._startlines
        if self._reslines is not None:
            ret['lines'] = self._reslines
        if self._detail is not None:
            ret['detail'] = self._detail

        ret['competitorA'] = self._competitorA
        # rankA: N/A (hold null)
        # downA: N/A (perhaps can indicate up/down on schedule)
        ret['timeA'] = self._timeA  # split time
        ret['infoA'] = self._infoA  # lap counter
        ret['labelA'] = self._labelA  # distance prefix
        ret['distance'] = self._distance  # distance

        # override lap count with auto laps, toGo will get lapscore output
        ret['laps'] = self._lapcount

        # rolling time
        if self._finish is not None:
            ret['startTime'] = self._start
            ret['endTime'] = self._finish
        elif self._lstart is not None:
            ret['startTime'] = self._lstart

        if len(self.decisions) > 0:
            ret['decisions'] = self.meet.decision_list(self.decisions)
        return ret

    def update_expander_lbl_cb(self):
        """Update race info expander label."""
        self.info_expand.set_label(self.meet.infoline(self.event))

    def editent_cb(self, entry, col):
        """Shared event entry update callback."""
        if col == 'pref':
            self.event['pref'] = entry.get_text()
        elif col == 'info':
            self.event['info'] = entry.get_text()

    def bibent_cb(self, entry, tp):
        """Bib entry callback."""
        bib = entry.get_text().strip().upper()
        if bib and bib.isalnum():
            self._rider = self.meet.rdb.get_rider(bib, self.series)
            self._updateRider()
        else:
            self._rider = None
            self._updateRider()

    def recover_start(self):
        """Recover missed start time"""
        if self.timerstat in ('idle', 'armstart'):
            rt = self.meet.recover_time(_CHAN_START)
            if rt is not None:
                # rt: (event, wallstart)
                _log.info('Recovered start time: %s', rt[0].rawtime(3))
                if self.timerstat == 'idle':
                    self.timerstat = 'armstart'
                self.meet.main_timer.dearm(_CHAN_START)
                self.torunning(rt[0], rt[1])
                self.recalculate()
            else:
                _log.info('No recent start time to recover')
        else:
            _log.info('Unable to recover start')

    def _starttrig(self, e):
        """Receive a start trigger."""
        if self.timerstat == 'armstart':
            _log.debug('Start trigger: %s@%s / %s', e.chan, e.rawtime(4),
                       e.source)
            self.torunning(e)
            self.recalculate()
        else:
            _log.debug('Spurious start trigger: %s@%s/%s', e.chan,
                       e.rawtime(1), e.source)

    def _laptrig(self, e):
        """Receive a lap trigger."""
        if self._start is not None:
            lt = self._start
            if self._splitlist:
                lt = self._splitlist[-1]  # last completed lap
            laptime = e - lt
            if laptime > self._minlap and laptime < self._reclen:
                self._prevlap = laptime
                rno = ''
                if self._rider is not None:
                    rno = self._rider['no']
                elap = e - self._start
                if elap < self._reclen:
                    # this is one more lap
                    self._lapcount += 1
                    self._splitlist.append(e)
                    self._timer.intermed(e)
                    if lt != self._start:
                        self.meet.timer_log_straight(rno, 'lap', laptime, 3)
                    self.meet.timer_log_straight(rno, str(self._lapcount),
                                                 elap, 3)
                    _log.debug('Lap %d @ %s : %s', self._lapcount,
                               elap.rawtime(1), laptime.rawtime(1))
                else:
                    if self._finish is None:
                        # this is the end
                        self._finish = e
                        self._lastlap = laptime
                        self._timer.finish(e)
                        _log.debug('Rider finished @ %s, last lap: %s',
                                   elap.rawtime(1), laptime.rawtime(1))
                        self.meet.timer_log_straight(rno, 'lap', laptime, 3)
                        self.meet.timer_log_straight(rno, 'fin', elap, 3)
                    else:
                        _log.debug(
                            'Sprious lap trigger after last lap: %s@%s/%s',
                            e.chan, e.rawtime(1), e.source)
                self.recalculate()
                GLib.idle_add(self.scblap)
            else:
                _log.debug('Short lap: %s', laptime.rawtime(1))
        else:
            _log.debug('Spurious lap trigger: %s@%s/%s', e.chan, e.rawtime(1),
                       e.source)

    def _halflaptrig(self, e):
        """Receive a half lap trigger."""
        pass

    def _mantrig(self, e):
        """Receive a manual lap trigger."""
        if self._start is not None:
            elap = e - self._start
            if elap < self._reclen:
                self._mancount += 1
                _log.debug('Man lap %d @ %s', self._mancount, e.rawtime(1))
            else:
                _log.debug('Man trig last lap: %s', e.rawtime(1))

    def timercb(self, e):
        """Handle a timer event."""
        if self._finish is not None:
            _log.debug('Event already finished')
            return False

        chan = strops.chan2id(e.chan)
        if chan == _CHAN_START:
            self._starttrig(e)
        elif chan == _CHAN_LAP:
            self._laptrig(e)
        elif chan == _CHAN_HALF:
            self._halflaptrig(e)
        elif chan == _CHAN_MAN:
            self._mantrig(e)
        return False

    def timeout(self):
        """Update scoreboard and respond to timing events."""
        if not self.winopen:
            return False

        now = tod.now()
        nelap = ''
        dofinishtxt = False
        dostarttxt = False
        if self._lstart is not None and self._finish is None:
            # running
            elap = now - self._lstart
            if elap >= (self._reclen + tod.mktod('5:00')):
                nelap = '--:--'
            else:
                nelap = elap.rawtime(0)

        elif self._finish is not None:
            # the hour is over
            nelap = '--:--'
            dofinishtxt = True
        else:
            # before start
            nelap = ''
            dostarttxt = True
            if self._wallstart is not None:
                count = self._wallstart - now
                if count >= tod.MINUTE and count < tod.HOUR:
                    nelap = count.rawtime(0)

        if self._timerwin and type(self.meet.scbwin) is scbwin.scbtt:
            if nelap != self._lelap or dofinishtxt:
                self._lelap = nelap
                if dofinishtxt:
                    self.meet.scbwin.setline1('')
                    self.meet.scbwin.setr1('Result:')
                    if self._D is not None and self._D > 0:
                        self.meet.scbwin.sett1('{0:0.3f}km'.format(self._D /
                                                                   1000.0))
                    else:
                        pass
                        ##! - whatados?
                    self.meet.scbwin.setline2('')
                    self.meet.scbwin.setr2('')
                    self.meet.scbwin.sett2('')
                elif dostarttxt:
                    if self._record:
                        self.meet.scbwin.setr1('Record:')
                        self.meet.scbwin.sett1('{0:0.3f}km'.format(
                            self._record / 1000.0))
                    elif self._target:
                        self.meet.scbwin.setr1('Target:')
                        self.meet.scbwin.sett1('{0:0.3f}km'.format(
                            self._target / 1000.0))
                    if self._wallstart is not None:
                        line1 = strops.truncpad(
                            'Start Time: ',
                            self.meet.scb.linelen - 12,
                            align='r') + strops.truncpad(
                                self._wallstart.meridiem(), 12, align='l')
                        self.meet.scbwin.setline2(line1)
                    if nelap:
                        self.meet.scbwin.setr2('Countdown:')
                        self.meet.scbwin.sett2(nelap)
                    else:
                        self.meet.scbwin.setr2('')
                        self.meet.scbwin.sett2('')
                    self.meet.scbwin.update()
                else:
                    self.scblap()

        if self._timer.status in ('running'):
            now = tod.now()
            self._timer.runtime(now - self._lstart)

        return True

    def scblap(self):
        """Update scoreboard and telegraph outputs."""

        if self._timerwin and type(self.meet.scbwin) is scbwin.scbtt:
            self.meet.scbwin.setline1(
                strops.truncpad(
                    'Elapsed: ', self.meet.scb.linelen - 12, align='r') +
                strops.truncpad(self._lelap, 12))

            if self._lapcount > 0 and len(self._splitlist) == self._lapcount:
                self.meet.scbwin.setr1('Lap {0}:'.format(self._lapcount))
                lstr = ''
                if self._prevlap is not None:
                    if self._prevlap < tod.MINUTE:
                        lstr = self._prevlap.rawtime(3)
                    else:
                        lstr = self._prevlap.rawtime(0)
                self.meet.scbwin.sett1(lstr)
            else:
                self.meet.scbwin.setline2('')
                self.meet.scbwin.setr1('')
                self.meet.scbwin.sett1('')
            if self._record:
                self.meet.scbwin.setline2(
                    strops.truncpad(
                        'Record: ', self.meet.scb.linelen - 12, align='r') +
                    strops.truncpad('{0:0.3f}km'.format(self._record /
                                                        1000.0), 12))
            elif self._target:
                self.meet.scbwin.setline2(
                    strops.truncpad(
                        'Target: ', self.meet.scb.linelen - 12, align='r') +
                    strops.truncpad('{0:0.3f}km'.format(self._target /
                                                        1000.0), 12))
            if self._projection is not None:
                self.meet.scbwin.setr2('Projection:')
                self.meet.scbwin.sett2('{0:0.1f}  km'.format(self._projection /
                                                             1000.0))
            else:
                self.meet.scbwin.setr2('')
                self.meet.scbwin.sett2('')
            self.meet.scbwin.update()

        # telegraph outputs
        self.meet.cmd_announce('lapcount', str(self._lapcount))
        self.meet.cmd_announce('elapsed', self._lelap)
        if self._prevlap is not None:
            self.meet.cmd_announce('laptime', self._prevlap.rawtime(3))

        ### on the gemini - use B/T dual timer mode
        ###self.meet.gemini.set_bib(str(self.lapcount),0)
        ###self.meet.gemini.set_time(self.lastlapstr,0)
        ###self.meet.gemini.set_time(self.elapsed,1)
        ###self.meet.gemini.show_dual()

        return False

    def result_gen(self):
        """Generator function to export a final result."""
        bib = ''
        rank = None
        if self._rider is not None:
            bib = self._rider['no']
            rank = 1
        time = None
        info = None
        if self._D:
            info = str(self._D)
        yield (bib, rank, time, info)

    def data_bridge(self):
        """Export data bridge fragments, startlists and results"""
        fragment = self.event.get_fragment()
        if fragment:
            data = self.data_pack()
            self.meet.db.updateFragment(self.event, fragment, data)

    def result_report(self, recurse=False):
        """Return a list of report sections containing the race result."""
        ret = []
        self.recalculate()
        self._reslines = None
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.bullet_text(secid)
        sec.nobreak = True
        sec.heading = self.event.get_info(showevno=True)
        # suppress "laps" on hour report
        subv = []
        if self._wallstart is not None:
            subv.append('Start: %s' % (self._wallstart.meridiem(secs=False), ))
        if self.event['record']:
            subv.append(self.event['record'])
        sec.subheading = '\u3000'.join(subv)

        # summary lines
        self._reslines = [{
            'rank': 1,
            'class': None,
            'competitor': None,
            'nation': None,
            'name': None,
            'pilot': None,
            'info': None,
            'result': None,
            'extra': None,
            'badges': [],
        }]
        resline = self._reslines[0]
        if self._rider is not None:
            sec.lines.append(['', self._riderName()])
            resline['competitor'] = self._rider['no']
            resline['nation'] = self._rider['nation']
            resline['name'] = self._rider.resname()
            resline['info'] = self._rider['class']
            ph = self.meet.rdb.get_pilot(self._rider)

            if ph is not None:
                resline['pilot'] = ph.resname()
        if self._weather is not None:
            wstr = 'Weather: %0.1f\u2006\u2103, %0.1f\u2006%%, %0.1f\u2006hPa' % (
                self._weather['t'],
                self._weather['h'],
                self._weather['p'],
            )
            sec.lines.append(['', wstr])

        # complete?
        if self._finish is not None:
            if self._D is not None and self._D > 0:
                resline['result'] = '{0:0.3f}\u2006km'.format(self._D / 1000.0)

                dstr = 'Final distance: {0:0.3f}\u2006km'.format(self._D /
                                                                 1000.0)
                sec.lines.append(['', dstr])
                if self._record is not None:
                    rstr = ''
                    if self._D > self._record:
                        # assume world record  ##! TODO: add record objects?
                        resline['badges'].append('wr')
                        delta = self._D - self._record
                        rstr = '{0}\u2006m more than record: {1:0.3f}\u2006km'.format(
                            delta, self._record / 1000.0)
                    else:
                        delta = self._record - self._D
                        if delta == 0:  # special case
                            rstr = 'Equalled record: {0:0.3f}\u2006km'.format(
                                self._record / 1000.0)
                        else:
                            rstr = '{0}\u2006m short of record: {1:0.3f}\u2006km'.format(
                                delta, self._record / 1000.0)

                    sec.lines.append(['', rstr])
            lstr = 'Complete laps: {0}'.format(self._lapcount)
            sec.lines.append(['', lstr])
            if self._compute:
                dicstr = 'Additional distance: {0}\u2006m'.format(self._DiC)
                sec.lines.append(['', dicstr])
                sec.lines.append(['', self._compute])
        elif self._start is not None:
            ## add elapsed ##! TODO
            if self._elapsed is not None:
                elapstr = 'Elapsed: %s' % (self._elapsed)
                sec.lines.append(['', elapstr])
            if self._lapcount > 0:
                lapstr = 'Complete laps: %d' % (self._lapcount, )
                sec.lines.append(['', lapstr])
            if self._avglap is not None:
                avgstr = '1\u2006km lap average: %0.3f\u2006s' % (
                    self._avglap, )
                sec.lines.append(['', avgstr])
            if self._projection is not None:
                projstr = 'Projection: %0.3f\u2006km' % (self._projection /
                                                         1000.0, )
                sec.lines.append(['', projstr])
        ret.append(sec)

        self._detail = None
        if self._start is not None and self._splitlist:
            self._detail = {}
            rno = ''
            if self._rider is not None:
                rno = self._rider['no']
            self._detail[rno] = {}
            detail = self._detail[rno]
            sec = report.threecol_section('laptimes')
            sec.subheading = 'Lap Times'
            lpi = self.meet.tracklen_n / self.meet.tracklen_d
            lt = self._start
            count = 1
            ld = 0
            for st in self._splitlist:
                laptime = st - lt
                split = st - self._start
                lstr = str(count)
                dist = int(lpi * count)
                detail[lstr] = {
                    'label': '%d\u2006m' % (dist, ),
                    'rank': None,
                    'elapsed': split.truncate(3),
                    'interval': laptime.truncate(3),
                    'points': None,
                }
                nd = int(0.010 + lpi * count / 1000.0)
                if nd != ld:
                    lstr += '  / {}\u2006km'.format(nd)
                    ld = nd
                sec.lines.append(
                    ['', '', lstr, '',
                     laptime.rawtime(3),
                     split.rawtime(3)])
                lt = st
                count += 1
            # include final lap
            if self._finish is not None and count > 0:
                laptime = self._finish - lt
                split = self._finish - self._start
                dist = int(lpi * count)
                lstr = str(count)
                detail[lstr] = {
                    'label': '%d\u2006m' % (dist, ),
                    'rank': None,
                    'elapsed': split.truncate(3),
                    'interval': laptime.truncate(3),
                    'points': None,
                }
                nd = int(0.010 + lpi * count / 1000.0)
                if nd != ld:
                    lstr += '  / {}\u2006km'.format(nd)
                    ld = nd
                sec.lines.append(
                    ['', '', lstr, '',
                     laptime.rawtime(3),
                     split.rawtime(3)])
            ret.append(sec)

        if len(self.decisions) > 0:
            ret.append(self.meet.decision_section(self.decisions))
        return ret

    def standingstr(self, width=None):
        """Return an event status string for reports and scb."""
        ret = ''
        if self._start is not None:
            ret = 'Virtual'
            if self._finish is not None:
                ret = 'Result'
        return ret

    def show(self):
        """Show race window."""
        self.frame.show()

    def hide(self):
        """Hide race window."""
        self._endtrace()
        self.frame.hide()

    def recalculate(self):
        """Update internal state."""
        self._avglap = None
        self._projection = None
        self._elapsed = None
        self._status = None

        self._competitorA = None
        self._timeA = None
        self._infoA = None
        self._labelA = None
        self._distance = None
        if self._detail is not None:
            ret['detail'] = self._detail
        if self._start is not None:
            lpi = self.meet.tracklen_n / self.meet.tracklen_d
            if self._finish is not None:
                self._status = 'provisional'
                llstart = self._start
                if self._splitlist:
                    llstart = self._splitlist[-1]

                # convert to plain values for calculation [3.5.031]
                tc = self._lapcount
                llelap = llstart - self._start
                trc = float((self._reclen - llelap).timeval)
                ttc = float(self._lastlap.timeval)
                dic = lpi * trc / ttc
                if dic > lpi:
                    _log.error('DiC %0.1f is greater than LPi %0.1f', dic, lpi)
                d = (lpi * tc) + dic
                self._D = int(floor(d))
                self._DiC = int(floor(dic))
                self._compute = 'Compute: D=%d\u2006m, LPi=%0.1f\u2006m, TC=%d\u2006lap%s, DiC=%d\u2006m, TTC=%0.3f\u2006s, TRC=%0.3f\u2006s' % (
                    self._D, lpi, tc, strops.plural(tc), self._DiC, ttc, trc)
                _log.debug('%s', self._compute)
                self._distance = '%0.3f\u2006km' % (self._D / 1000.0)
            else:
                self._status = 'virtual'
                if self._lapcount > 0 and len(
                        self._splitlist) == self._lapcount:
                    lastpass = self._splitlist[-1]
                    elap = lastpass - self._start
                    self._elapsed = elap.rawtime(1)
                    remain = tod.HOUR - elap
                    remsec = float(remain.timeval)
                    self._distance = '%0.3f\u2006km' % (lpi * self._lapcount /
                                                        1000.0)

                    if len(self._splitlist) > 7:  # ignore first km
                        st = self._splitlist[-5]
                        et = self._splitlist[-1]
                        elap = et - st
                        minelap = 4 * float(self._minlap.timeval)
                        if elap > minelap and elap < _MAXAVG:
                            self._avglap = 0.25 * float(elap.timeval)

                    if len(self._splitlist
                           ) >= self._projlap and self._avglap is not None:
                        if remain > self._minlap:
                            pcount = self._lapcount + _PESSIMISM * remsec / self._avglap
                            proj = lpi * pcount
                            _log.debug(
                                'Projection:  Avg=%0.1fs, Rem=%0.1fs, Count=%0.1fs, Proj=%0.1fs',
                                self._avglap, remsec, pcount, proj)
                            if proj > self._minproj and proj < self._maxproj:
                                self._projection = int(proj)

                    if self._avglap is not None:
                        twolaps = 2 * self._avglap
                        if remsec < twolaps and remsec > self._avglap:
                            _log.warning('BELL NEXT LAP')
                            ##! TODO - flag in ui
                else:
                    _log.debug(
                        'Laps (%d) and splits (%d) out, projection skipped',
                        self._lapcount, len(self._splitlist))
        else:
            pass

        if self.winopen:
            # update user interface with runtime info
            pass

    def __init__(self, meet, event, ui=True):
        """Constructor.

        Parameters:

            meet -- handle to meet object
            event -- event object handle
            ui -- display user interface?

        """
        self.meet = meet
        self.event = event
        self.evno = event['evid']
        self.evtype = event['type']
        self.series = event['series']
        self.configfile = meet.event_configfile(self.evno)
        self.timerstat = 'idle'

        self.readonly = not ui
        rstr = ''
        if self.readonly:
            rstr = 'readonly '
        _log.debug('Init %sevent %s', rstr, self.evno)

        self.decisions = []  # list of decisions of the officials
        self.onestart = False  # event started/running or complete
        self.winopen = ui  # event user interface is loaded
        self.finished = False  # event complete - all competitors accounted for

        self._winState = {}  # cache config values when no ui present

        # configs
        self._reclen = _DURATION
        self._minlap = _MINLAP
        self._wallstart = None
        self._record = None
        self._target = None
        self._projlap = _PROJLAP
        self._minproj = _MINPROJ
        self._maxproj = _MAXPROJ

        # runstate
        self._startlines = None
        self._reslines = None
        self._detail = None
        self._competitorA = None
        self._infoA = None
        self._timeA = None
        self._labelA = None
        self._distance = None
        self._rider = None  # rider handle for competitor
        self._weather = None  # weather observations at start of event
        self._start = None  # hour start by chronometer
        self._lstart = None  # rolling time start
        self._finish = None  # finish time by chronometer
        self._elapsed = None  # current elapsed time
        self._lelap = None  # last elapsed time displayed on scb
        self._projection = None  # current projection at finish
        self._avglap = None  # current lap average
        self._lapcount = 0  # lap count
        self._mancount = 0  # manual/backup lap count
        self._lastlap = None  # lap time in which hour expired
        self._prevlap = None  # most recent lap time
        self._splitlist = []  # list of lap split times
        self._trace = None
        self._tracelog = []
        self._abortcnt = 0  # make abort difficult
        self._timerwin = False
        self._status = None

        # computes
        self._compute = None  # compute string for report
        self._D = 0
        self._TC = 0
        self._DiC = 0
        self._TTC = None
        self._TRC = None

        if ui:
            b = uiutil.builder('hourrec.ui')
            self.frame = b.get_object('race_vbox')

            # info pane
            self.info_expand = b.get_object('info_expand')
            b.get_object('race_info_evno').set_text(self.evno)
            self.showev = b.get_object('race_info_evno_show')
            self.prefix_ent = b.get_object('race_info_prefix')
            self.prefix_ent.set_text(self.event['pref'])
            self.prefix_ent.connect('changed', self.editent_cb, 'pref')
            self.info_ent = b.get_object('race_info_title')
            self.info_ent.set_text(self.event['info'])
            self.info_ent.connect('changed', self.editent_cb, 'info')

            # Timer Pane
            mf = b.get_object('race_timer_pane')
            self._timer = uiutil.timerpane('Timer', doser=False)
            self._timer.bibent.connect('activate', self.bibent_cb, self._timer)
            self._timer.hide_splits()
            mf.pack_start(self._timer.frame, True, True, 0)

            b.connect_signals(self)
