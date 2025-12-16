# SPDX-License-Identifier: MIT
"""Generic race handler for trackmeet."""

import os
import gi
import logging
from random import shuffle

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

_log = logging.getLogger('race')
_log.setLevel(logging.DEBUG)

# config version string
EVENT_ID = 'race-2.2'

# race model column constants
COL_NO = 0
COL_NAME = 1
COL_RSVD1 = 2
COL_RSVD2 = 3
COL_INFO = 4
COL_INRACE = 5
COL_PLACE = 6
COL_DNFCODE = 7

# scb function key mappings
key_startlist = 'F3'  # show starters in table
key_results = 'F4'  # recalc/show result window
key_lapdown = 'F11'  # decrement tv lap counter

# timing function key mappings
key_armstart = 'F5'  # arm for start/200m impulse
key_showtimer = 'F6'  # show timer
key_armfinish = 'F9'  # arm for finish impulse

# extended function key mappings
key_abort = 'F5'  # + ctrl for clear/abort
key_falsestart = 'F6'  # + ctrl for false start


class race:
    """Data handling for elimination, handicap, keirin, derby, etc races."""

    def force_running(self, start=None):
        """Set event timer to running."""
        if start is None:
            start = tod.now()
        if self.timerstat in ('idle', 'armstart') and self.timetype != '200m':
            self.timerstat = 'armstart'
            self.starttrig(start, wallstart=start)
            self.meet.set_event_start(self.event)
        elif self.timerstat in ('running', 'armfinish'):
            if self.start is not None:
                self.timerstat = 'armfinish'
                self.fintrig(start)
        self.resend_current()

    def show_lapscore(self, laps, prev):
        """Accept laps when idle/running"""

        # reject elimination
        if self.evtype == 'elimination':
            return False

        # otherwise use the ps method
        ret = False
        if self.event['laps'] and prev is not None and laps is not None:
            if prev - laps == 1:  # only announce decrement
                if self.timerstat == 'idle':
                    # check for a missed start
                    stlap = self.event['laps'] - 1
                    if laps == stlap and self.timetype != '200m':
                        self.force_running(tod.now() - tod.mktod(20))
                    ret = True
                elif self.timerstat in ('running', 'armfinish'):
                    ret = True
        return ret

    def ridercb(self, rider):
        """Rider change notification"""
        if self.winopen:
            if rider is not None:
                rno = rider[0]
                series = rider[1]
                if series == self.series:
                    dbr = self.meet.rdb[rider]
                    rh = self._getrider(rno)
                    if rh is not None:
                        _log.debug('Rider change notify: %r', rider)
                        rh[COL_NAME] = dbr.listname()
            else:
                # riders db changed, handled by meet object
                pass

    def eventcb(self, event):
        """Event change notification function"""
        if self.winopen:
            if event is None or event == self.evno:
                if self.prefix_ent.get_text() != self.event['pref']:
                    self.prefix_ent.set_text(self.event['pref'])
                if self.info_ent.get_text() != self.event['info']:
                    self.info_ent.set_text(self.event['info'])
                # re-draw summary line
                self.update_expander_lbl_cb()

    def changerider(self, oldNo, newNo):
        """Update rider no in event"""
        oldNo = oldNo.upper()
        newNo = newNo.upper()
        if self.inevent(oldNo):
            if oldNo != newNo and not self.inevent(newNo):
                name = ''
                dbr = self.meet.rdb.get_rider(newNo, self.series)
                if dbr is not None:
                    name = dbr.listname()
                for r in self.riders:
                    if r[COL_NO] == oldNo:
                        _log.debug('Updating number %s -> %s in event %s',
                                   oldNo, newNo, self.evno)
                        r[COL_NO] = newNo
                        r[COL_NAME] = name
                        break
                nelim = []
                for r in self.eliminated:
                    if r == oldNo:
                        _log.debug('Updating withdrawn %s -> %s in event %s',
                                   oldNo, newNo, self.evno)
                        nelim.append(newNo)
                    else:
                        nelim.append(r)
                self.eliminated = nelim
                newPlaces = []
                oldPlaces = self.places.upper()
                for placeGroup in oldPlaces.split():
                    ng = []
                    for r in placeGroup.split('-'):
                        r = r.strip()
                        if r == oldNo:
                            _log.debug('Updating placed %s -> %s in event %s',
                                       oldNo, newNo, self.evno)
                            ng.append(newNo)
                        else:
                            if r:
                                ng.append(r)
                    newPlaces.append('-'.join(ng))
                self.placexfer(' '.join(newPlaces))
                return True
        return False

    def inevent(self, bib):
        """Return true if rider appears in model."""
        return self._getrider(bib) is not None

    def _getrider(self, bib):
        """Return temporary reference to model row."""
        bib = bib.upper()
        ret = None
        for r in self.riders:
            if r[COL_NO] == bib:
                ret = r
                break
        return ret

    def _getiter(self, bib):
        """Return temporary iterator to model row."""
        bib = bib.upper()
        i = self.riders.get_iter_first()
        while i is not None:
            if self.riders.get_value(i, COL_NO) == bib:
                break
            i = self.riders.iter_next(i)
        return i

    def delayed_reorder(self):
        """Call reorder if the flag is one."""
        if self.reorderflag > 1:
            self.reorderflag -= 1
        elif self.reorderflag == 1:
            self.reorder_riders()
            self.reorderflag = 0
        else:
            self.reorderflag = 0  # clamp negatives
        return False

    def addrider(self, bib='', info=None):
        """Add specified rider to race model."""
        bib = bib.upper()
        er = self._getrider(bib)
        if not bib or er is None:
            nr = [bib, '', '', '', '', True, '', '']
            dbr = self.meet.rdb.get_rider(bib, self.series)
            if dbr is not None:
                nr[COL_NAME] = dbr.listname()
            if self.evtype == 'handicap':
                if info:
                    nr[COL_INFO] = strops.mark2mark(info)
                else:
                    if dbr is not None:
                        nr[COL_INFO] = strops.mark2mark(dbr['seed'])
            self.riders.append(nr)
        else:
            if er is not None:
                # Rider already in the model, set the info if
                # event type is handicap or event is part of omnium
                if not er[COL_INFO] and info:  # don't overwrite
                    if self.evtype == 'handicap':
                        er[COL_INFO] = strops.mark2mark(info)
                    elif self.inomnium:
                        er[COL_INFO] = str(info)

    def dnfriders(self, biblist='', dnfcode='dnf'):
        """Remove listed bibs from the race."""
        recalc = False
        for bib in biblist.split():
            r = self._getrider(bib)
            if r is not None:
                r[COL_INRACE] = False
                r[COL_DNFCODE] = dnfcode
                recalc = True
                _log.info('Rider %r out: %r', bib, dnfcode)
            else:
                _log.warning('Rider %r not in race', bib)
        if recalc:
            self.recalculate()
            self.meet.delayed_export()
        return False

    def delrider(self, bib):
        """Remove the specified rider from the model."""
        bib = bib.upper()

        inRes = False
        if bib in self.eliminated:
            self.eliminated.remove(bib)
            inRes = True
        newPlaces = []
        oldPlaces = self.places.upper()
        for placeGroup in oldPlaces.split():
            ng = []
            for r in placeGroup.split('-'):
                r = r.strip()
                if r == bib:
                    inRes = True
                else:
                    ng.append(r)
            newPlaces.append('-'.join(ng))
        if inRes:
            self.placexfer(' '.join(newPlaces))
            _log.warning('Removed rider %r from event %r result', bib,
                         self.evno)

        i = self._getiter(bib)
        if i is not None:
            self.riders.remove(i)
            self.recalculate()

    def _getresname(self, bib):
        """Return resline style name"""
        name = None
        nation = None
        dbr = self.meet.rdb.get_rider(bib, self.series)
        if dbr is not None:
            name = dbr.resname()
            nation = dbr['nation']
        return name, nation

    def _getname(self, bib, width=32):
        """Return a name, club and class label for the rider if known"""
        name = ''
        club = ''
        cls = ''
        dbr = self.meet.rdb.get_rider(bib, self.series)
        if dbr is not None:
            name = dbr.fitname(width)
            club = dbr['organisation']
            cls = dbr['class']
        return name, club, cls

    def recalculate(self):
        self.placexfer()
        return False

    def placexfer(self, places=None):
        """Transfer places to model."""
        if places is not None:
            self.places = places
        self.finished = False
        self.results = []
        placeset = set()
        # 12.456_[name]_123M
        resname_w = self.meet.scb.linelen - 12  # (3 + 3 + 1 + 5)

        # reset places and dnf codes, count riders
        cnt = 0
        incnt = 0
        if len(self.riders) > 0:
            for r in self.riders:
                if r[COL_INRACE]:
                    r[COL_PLACE] = ''
                    incnt += 1
                else:
                    # transfer dnfcode to place string
                    if not r[COL_DNFCODE]:
                        r[COL_DNFCODE] = 'dnf'
                    r[COL_PLACE] = r[COL_DNFCODE]
                cnt += 1

        # update withdrawn/eliminated rider places
        outriders = []
        for bib in self.eliminated:
            r = self._getrider(bib)
            if r is None:  # ensure rider exists at this point
                _log.debug('Added non-starter %r to event %r', bib, self.evno)
                self.addrider(bib)
                r = self._getrider(bib)

            name, club, nfo = self._getname(bib, width=resname_w)
            rank = incnt
            r[COL_PLACE] = str(rank)
            if r[COL_INFO]:
                if self.evtype not in (
                        'sprint',
                        'keirin',
                ) and not self.inomnium:
                    nfo = r[COL_INFO]
            outriders.insert(0, [str(rank) + '.', bib, name, nfo])
            incnt -= 1

        # overwrite eliminations from placed riders
        place = 1
        count = 0
        clubmode = self.meet.get_clubmode()
        for placegroup in self.places.split():
            for bib in placegroup.split('-'):
                if bib not in placeset:
                    if count >= incnt and not clubmode:
                        _log.warning(
                            'More places in event %r result than available',
                            self.evno)
                    placeset.add(bib)
                    r = self._getrider(bib)
                    if r is None:  # ensure rider exists at this point
                        _log.debug('Added non-starter %r to event %r', bib,
                                   self.evno)
                        self.addrider(bib)
                        r = self._getrider(bib)
                    rank = place
                    r[COL_PLACE] = str(rank)
                    name, club, nfo = self._getname(bib, width=resname_w)
                    if r[COL_INFO]:
                        if self.evtype not in (
                                'sprint',
                                'keirin',
                        ) and not self.inomnium:
                            nfo = r[COL_INFO]
                    self.results.append([str(rank) + '.', bib, name, nfo])
                    count += 1
                else:
                    _log.error('Ignoring duplicate no: %r', bib)
            place = count + 1
        for r in outriders:
            rno = r[1]
            if rno not in placeset:
                self.results.append(r)
            else:
                _log.info('Eliminated rider %s placed', rno)
                self.eliminated.remove(rno)

        # re-order model
        if len(self.riders) > 0:
            aux = []
            for cnt, r in enumerate(self.riders):
                rno = strops.riderno_key(r[COL_NO])
                dnfcode = strops.dnfcode_key(None)
                rank = 9998
                if not r[COL_INRACE]:
                    if r[COL_DNFCODE]:
                        dnfcode = strops.dnfcode_key(r[COL_DNFCODE])
                    else:
                        dnfcode = strops.dnfcode_key('dnf')
                    rank = 9999
                else:
                    if r[COL_PLACE] and r[COL_PLACE].isdigit():
                        rank = int(r[COL_PLACE])
                aux.append((rank, dnfcode, rno, cnt))
            aux.sort()
            self.riders.reorder([a[3] for a in aux])

        if count > 0 or len(outriders) > 0:
            self.onestart = True
        self._status = None
        self._remain = None
        if count == incnt:
            if self.onestart:
                self.resulttype = 'RESULT'
                self.finished = True
                self._status = 'provisional'
        elif count < incnt and len(outriders) > 0:
            self.resulttype = 'STANDING'
            self._status = 'virtual'
            self._remain = incnt
        else:
            self.resulttype = 'PROVISIONAL RESULT'
            if self.onestart:
                self._status = 'provisional'

    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        # set defaults timetype based on event type
        deftimetype = 'start/finish'
        defdistance = None
        defdistunits = 'laps'
        self.seedsrc = None  # default is no seed info
        if self.evtype == 'handicap':
            self.seedsrc = 3  # fetch handicap info from autospec
        if self.evtype in ('sprint', 'keirin'):
            deftimetype = '200m'
            defdistunits = 'metres'
            defdistance = '200'
        if self.winopen:
            if self.evtype == 'elimination':
                i = self.action_model.append(['Eliminate', 'out'])
                self.action_model.append(['Un-Eliminate', 'in'])
                if i is not None:
                    self.ctrl_action_combo.set_active_iter(i)
            else:
                self.action_model.append(['Withdraw', 'out'])
                self.action_model.append(['Un-Withdraw', 'in'])
        cr = jsonconfig.config({
            'event': {
                'startlist': '',
                'id': EVENT_ID,
                'ctrl_places': '',
                'eliminated': [],
                'start': None,
                'lstart': None,
                'decisions': [],
                'finish': None,
                'distance': defdistance,
                'distunits': defdistunits,
                'showinfo': False,
                'inomnium': False,
                'timetype': deftimetype,
                'weather': None,
            },
            'riders': {}
        })
        cr.add_section('event')
        cr.add_section('riders')
        if not cr.load(self.configfile):
            _log.info('%r not read, loading defaults', self.configfile)

        self.inomnium = strops.confopt_bool(cr.get('event', 'inomnium'))
        if self.inomnium:
            self.seedsrc = 1  # fetch start list seeding from omnium
        rlist = cr.get('event', 'startlist').upper().split()
        for r in rlist:
            ## TODO: replace rider lines
            nr = [r, '', '', '', '', True, '', '']
            if cr.has_option('riders', r):
                ril = cr.get('riders', r)
                for i in range(4):
                    if len(ril) > i:
                        nr[i + 4] = ril[i]
            # Re-patch name
            dbr = self.meet.rdb.get_rider(r, self.series)
            if dbr is not None:
                nr[COL_NAME] = dbr.listname()
            self.riders.append(nr)

        # race infos
        self._weather = cr.get('event', 'weather')
        self.decisions = cr.get('event', 'decisions')
        self.set_timetype(cr.get('event', 'timetype'))
        self.distance = strops.confopt_dist(cr.get('event', 'distance'))
        self.units = strops.confopt_distunits(cr.get('event', 'distunits'))
        if self.timetype != '200m' and self.event['laps']:
            # use event program to override
            self.units = 'laps'
            self.distance = strops.confopt_posint(self.event['laps'],
                                                  self.distance)
        self.set_start(cr.get('event', 'start'), cr.get('event', 'lstart'))
        self.set_finish(cr.get('event', 'finish'))
        self.set_elapsed()
        self.eliminated = cr.get('event', 'eliminated')
        self.places = strops.reformat_placelist(cr.get('event', 'ctrl_places'))

        if self.winopen:
            self.update_expander_lbl_cb()
            self.info_expand.set_expanded(
                strops.confopt_bool(cr.get('event', 'showinfo')))
            self.ctrl_places.set_text(self.places)
        else:
            self._winState['showinfo'] = cr.get('event', 'showinfo')

        self.recalculate()
        if self.places:
            self.doscbplaces = False  # only show places on board if not set
            self.setfinished()
        else:
            if not self.onestart and self.event['auto']:
                self.riders.clear()
                self.meet.autostart_riders(self,
                                           self.event['auto'],
                                           infocol=self.seedsrc)
            if self.evtype in ('handicap', 'keirin') or self.inomnium:
                self.reorder_riders()

        # After load complete - check config and report.
        eid = cr.get('event', 'id')
        if eid and eid != EVENT_ID:
            _log.info('Event config mismatch: %r != %r', eid, EVENT_ID)

    def reorder_riders(self):
        """Reorder rider model according to seeding or handicap marks."""
        if len(self.riders) > 1:
            auxmap = []
            cnt = 0
            for r in self.riders:
                seed = strops.mark2int(r[COL_INFO])
                if seed is None:
                    seed = 9999
                rno = strops.riderno_key(r[COL_NO])
                if self.evtype == 'handicap':
                    auxmap.append((
                        -seed,
                        rno,
                        cnt,
                    ))
                elif self.inomnium:
                    auxmap.append((
                        seed,
                        rno,
                        cnt,
                    ))
                else:
                    auxmap.append((
                        rno,
                        cnt,
                        cnt,
                    ))
                cnt += 1
            auxmap.sort()
            self.riders.reorder([a[2] for a in auxmap])

    def set_timetype(self, data=None):
        """Update state and ui to match timetype."""
        if data is not None:
            self.timetype = strops.confopt_pair(data, '200m', 'start/finish')
            self.finchan = 1
            if self.timetype == '200m':
                self.startchan = 4
            else:
                self.startchan = 0

    def set_start(self, start=None, lstart=None):
        """Set the race start."""
        self.start = tod.mktod(start)
        if lstart is not None:
            self.lstart = tod.mktod(lstart)
        else:
            self.lstart = self.start
        if self.start is None:
            pass
        else:
            if self.finish is None:
                self.setrunning()

    def set_finish(self, finish=None):
        """Set the race finish."""
        self.finish = tod.mktod(finish)
        if self.finish is None:
            if self.start is not None:
                self.setrunning()
        else:
            if self.start is None:
                self.set_start(0)  # TODO: Verify this path
            self.setfinished()

    def log_elapsed(self):
        """Log race elapsed time on Timy."""
        self.meet.main_timer.printline(self.meet.racenamecat(self.event))
        self.meet.main_timer.printline('      ST: ' + self.start.timestr(4))
        self.meet.main_timer.printline('     FIN: ' + self.finish.timestr(4))
        self.meet.main_timer.printline('    TIME: ' +
                                       (self.finish - self.start).timestr(2))

    def set_elapsed(self):
        """Update elapsed time in race ui and announcer."""
        if self.winopen:
            if self.start is not None and self.finish is not None:
                et = self.finish - self.start
                self.time_lbl.set_text(et.timestr(2))
            elif self.start is not None:  # Note: uses 'local start' for RT
                runtm = (tod.now() - self.lstart).timestr(1)
                self.time_lbl.set_text(runtm)
            elif self.timerstat == 'armstart':
                self.time_lbl.set_text('       0.0   ')  # tod.ZERO.timestr(1)
            else:
                self.time_lbl.set_text('')

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        if self.winopen:
            # clear page
            self.meet.txt_clear()
            self.meet.txt_title(self.event.get_info(showevno=True))
            self.meet.txt_line(1)
            self.meet.txt_line(19)

            # write out riders
            count = 0
            curline = 4
            posoft = 0
            for r in self.riders:
                count += 1
                if count == 14:
                    curline = 4
                    posoft = 41
                xtra = '    '
                if r[COL_INFO]:
                    inf = r[COL_INFO]
                    if self.evtype in ['keirin', 'sprint']:  # encirc draw no
                        inf = strops.drawno_encirc(inf)
                    xtra = strops.truncpad(inf, 4, 'r')
                namestr = strops.truncpad(r[COL_NAME], 25)
                places = '   '
                if r[COL_PLACE] != '':
                    places = strops.truncpad(r[COL_PLACE] + '.', 3)
                elif not r[COL_INRACE]:
                    places = r[COL_DNFCODE]
                bibstr = strops.truncpad(r[COL_NO], 3, 'r')
                self.meet.txt_postxt(curline, posoft,
                                     ' '.join([places, bibstr, namestr, xtra]))
                curline += 1

            tp = ''
            if self.start is not None and self.finish is not None:
                et = self.finish - self.start
                if self.timetype == '200m':
                    tp = '200m: '
                else:
                    tp = 'Time: '
                tp += et.timestr(2) + '    '
                dist = self.meet.get_distance(self.distance, self.units)
                if dist:
                    tp += 'Avg: ' + et.speedstr(dist)
            self.meet.txt_setline(21, tp)
            self.resend_current()
        return False

    def startlist_report(self, program=False):
        """Return a startlist report."""
        ret = []
        sec = None
        etype = self.event['type']
        twocol = True
        rankcol = None
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.twocol_startlist(secid)

        sec.nobreak = True
        headvec = self.event.get_info(showevno=True).split()
        if not program:
            headvec.append('Start List')
        else:
            rankcol = ' '
        sec.heading = ' '.join(headvec)
        lapstring = strops.lapstring(self.event['laps'])
        substr = '\u3000'.join(
            (lapstring, self.event['distance'], self.event['rules'])).strip()
        if substr:
            sec.subheading = substr

        self._startlines = []
        self.reorder_riders()
        sec.lines = []
        cnt = 0
        col2 = []
        if self.inomnium and len(self.riders) > 0:
            sec.lines.append((' ', ' ', 'Sprinters Lane', None, None, None))
            col2.append((' ', ' ', 'Fence', None, None, None))
        for r in self.riders:
            cnt += 1
            rno = r[COL_NO]
            rh = self.meet.rdb.get_rider(rno, self.series)
            rname = ''
            rnat = None
            pilot = None
            inf = ''
            if rh is not None:
                rname = rh.resname()
                rnat = rh['nation']
                inf = rh['class']
                pilot = self.meet.rdb.get_pilot_line(rh)

            if r[COL_INFO] and not self.inomnium:
                inf = r[COL_INFO]
            if self.evtype in ['keirin', 'sprint']:  # encirc draw no
                inf = strops.drawno_encirc(inf)
            if self.inomnium:
                if cnt % 2 == 0:
                    sec.lines.append([rankcol, rno, rname, inf, None, None])
                    if pilot:
                        sec.lines.append(pilot)
                else:
                    col2.append([rankcol, rno, rname, inf, None, None])
                    if pilot:
                        col2.append(pilot)
            else:
                sec.lines.append([rankcol, rno, rname, inf, None, None])
                if pilot:
                    sec.lines.append(pilot)
            # team members
            pname = None
            if pilot:
                pname = pilot[2]
            self._startlines.append({
                'competitor': rno,
                'nation': rnat,
                'name': rname,
                'info': inf,
                'pilot': pname,
            })

        # correct a mismatch in column length
        if col2:
            while len(sec.lines) < len(col2):
                sec.lines.append([' ', ' ', None])
            while len(col2) < len(sec.lines):
                col2.append([' ', ' ', None])

            for i in col2:
                sec.lines.append(i)
        else:
            if self.event['plac']:
                while cnt < self.event['plac']:
                    sec.lines.append([rankcol, None, None, None, None, None])
                    cnt += 1

        # Prizemoney line
        sec.prizes = self.meet.prizeline(self.event)

        # Footer line
        sec.footer = self.meet.footerline(self.event, count=cnt)

        ret.append(sec)
        return ret

    def get_startlist(self):
        """Return a list of bibs in the rider model."""
        ret = []
        for r in self.riders:
            ret.append(r[COL_NO])
        return ' '.join(ret)

    def saveconfig(self):
        """Save race to disk."""
        if self.readonly:
            _log.error('Attempt to save readonly event')
            return
        cw = jsonconfig.config()
        cw.add_section('event')
        cw.set('event', 'start', self.start)
        cw.set('event', 'lstart', self.lstart)
        cw.set('event', 'finish', self.finish)
        cw.set('event', 'ctrl_places', self.places)
        cw.set('event', 'eliminated', self.eliminated)
        cw.set('event', 'startlist', self.get_startlist())
        if self.winopen:
            cw.set('event', 'showinfo', self.info_expand.get_expanded())
        else:
            cw.set('event', 'showinfo', self._winState['showinfo'])
        cw.set('event', 'distance', self.distance)
        cw.set('event', 'distunits', self.units)
        cw.set('event', 'timetype', self.timetype)
        cw.set('event', 'weather', self._weather)
        cw.set('event', 'inomnium', self.inomnium)
        cw.set('event', 'decisions', self.decisions)

        cw.add_section('riders')
        for r in self.riders:
            cw.set('riders', r[COL_NO],
                   [r[COL_INFO], r[COL_INRACE], r[COL_PLACE], r[COL_DNFCODE]])
        cw.set('event', 'id', EVENT_ID)
        _log.debug('Saving event config %r', self.configfile)
        with metarace.savefile(self.configfile) as f:
            cw.write(f)

    def do_properties(self):
        """Run event properties dialog."""
        b = uiutil.builder('race_properties.ui')
        dlg = b.get_object('properties')
        dlg.set_transient_for(self.meet.window)
        rt = b.get_object('race_score_type')
        if self.timetype != '200m':
            rt.set_active(0)
        else:
            rt.set_active(1)
        di = b.get_object('race_dist_entry')
        if self.distance is not None:
            di.set_text(str(self.distance))
        else:
            di.set_text('')
        du = b.get_object('race_dist_type')
        if self.units == 'metres':
            du.set_active(0)
        else:
            du.set_active(1)
        se = b.get_object('race_series_entry')
        se.set_text(self.series)
        as_e = b.get_object('auto_starters_entry')
        as_e.set_text(self.event['starters'])
        response = dlg.run()
        if response == 1:  # id 1 set in glade for "Apply"
            _log.debug('Updating event properties')
            if rt.get_active() == 0:
                self.set_timetype('start/finish')
            else:
                self.set_timetype('200m')
            dval = di.get_text()
            if dval.isdigit():
                self.distance = int(dval)
            else:
                self.distance = None
            if du.get_active() == 0:
                self.units = 'metres'
            else:
                self.units = 'laps'

            # update series
            ns = se.get_text()
            if ns != self.series:
                self.series = ns
                self.event['seri'] = ns

            # update auto startlist spec in event db
            nspec = as_e.get_text()
            if nspec != self.event['starters']:
                self.event.set_value('starters', nspec)
                if not self.ctrl_places.get_text():
                    self.riders.clear()
                    if nspec:
                        self.meet.autostart_riders(self, nspec, self.seedsrc)
                    if self.evtype == 'handicap':
                        self.reorder_riders()

            # xfer starters if not empty
            slist = strops.riderlist_split(
                b.get_object('race_starters_entry').get_text(), self.meet.rdb,
                self.series)
            for s in slist:
                self.addrider(s)
            # recalculate
            self.recalculate()
            GLib.idle_add(self.delayed_announce)
        else:
            _log.debug('Edit event properties cancelled')

        # if prefix is empty, grab input focus
        if not self.prefix_ent.get_text():
            self.prefix_ent.grab_focus()
        dlg.destroy()

    def resettimer(self):
        """Reset race timer."""
        self.finish = None
        self.start = None
        self.lstart = None
        self.timerstat = 'idle'
        self.eliminated = []
        self._status = None
        self._weather = None
        self._startlines = None
        self._reslines = None
        self._remain = None
        self._eliminated = None
        self.ctrl_places.set_text('')
        self.placexfer('')
        self.meet.main_timer.dearm(self.startchan)
        self.meet.main_timer.dearm('C0')
        self.meet.main_timer.dearm(self.finchan)
        self.stat_but.update('idle', 'Idle')
        self.stat_but.set_sensitive(True)
        self.set_elapsed()
        _log.info('Event reset - all places cleared')

    def setrunning(self):
        """Set timer state to 'running'."""
        self.timerstat = 'running'
        if self.winopen:
            self.stat_but.update('ok', 'Running')

    def setfinished(self):
        """Set timer state to 'finished'."""
        self.timerstat = 'finished'
        if self.winopen:
            self.stat_but.update('idle', 'Finished')
            self.stat_but.set_sensitive(False)
            self.ctrl_places.grab_focus()

    def armstart(self):
        """Toggle timer arm start state."""
        if self.timerstat == 'idle':
            self.timerstat = 'armstart'
            self.stat_but.update('activity', 'Arm Start')
            self.meet.main_timer.arm(self.startchan)
            if self.timetype == '200m':
                # also accept C0 on sprint types
                self.meet.main_timer.arm(0)
        elif self.timerstat == 'armstart':
            self.timerstat = 'idle'
            self.time_lbl.set_text('')
            self.stat_but.update('idle', 'Idle')
            self.meet.main_timer.dearm(self.startchan)
            self.meet.main_timer.dearm('C0')

    def armfinish(self):
        """Toggle timer arm finish state."""
        if self.timerstat == 'running':
            self.timerstat = 'armfinish'
            self.stat_but.update('error', 'Arm Finish')
            self.meet.main_timer.arm(self.finchan)
        elif self.timerstat == 'armfinish':
            self.timerstat = 'running'
            self.stat_but.update('ok', 'Running')
            self.meet.main_timer.dearm(self.finchan)
        return False  # for use in delayed callback

    def showtimer(self):
        """Display the running time on the scoreboard."""
        if self.timerstat == 'idle':
            self.armstart()
        tp = 'Time:'
        if self.timetype == '200m':
            tp = '200m:'
        self.meet.cmd_announce('eliminated', '')
        self._eliminated = None
        self.meet.scbwin = scbwin.scbtimer(scb=self.meet.scb,
                                           line1=self.meet.racenamecat(
                                               self.event),
                                           line2='',
                                           timepfx=tp)
        wastimer = self.timerwin
        self.timerwin = True
        if self.timerstat == 'finished':
            if not wastimer:
                self.meet.scbwin.reset()
            if self.start is not None and self.finish is not None:
                elap = self.finish - self.start
                self.meet.scbwin.settime(elap.timestr(2))
                dist = self.meet.get_distance(self.distance, self.units)
                if dist:
                    self.meet.scbwin.setavg(elap.speedstr(dist))
            self.meet.scbwin.update()
        else:
            self.meet.scbwin.reset()
        self.resend_current()

    def _do_draw(self):
        """Clear, shuffle and re-draw for sprint/keirin"""
        tot = 0
        for r in self.riders:
            if r[COL_INRACE]:
                tot += 1
        draw = [d for d in range(1, tot + 1)]
        shuffle(draw)
        idx = 0
        for r in self.riders:
            if r[COL_INRACE]:
                r[COL_INFO] = str(draw[idx])
                idx += 1

    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == Gdk.EventType.KEY_PRESS:
            key = Gdk.keyval_name(event.keyval) or 'None'
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                if key == key_abort:  # override ctrl+f5
                    self.resettimer()
                    return True
                elif key == key_startlist:
                    if self.evtype in ['keirin', 'sprint']:
                        self._do_draw()
                        return True
            if key[0] == 'F':
                if key == key_armstart:
                    self.armstart()
                    return True
                elif key == key_armfinish:
                    self.armfinish()
                    return True
                elif key == key_showtimer:
                    self.showtimer()
                    return True
                elif key == key_startlist:
                    self.do_startlist()
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_results:
                    self.doscbplaces = True  # override if already clear
                    self.do_places()  # also triggers recalc
                    GLib.idle_add(self.delayed_announce)
                    return True
        return False

    def do_places(self):
        """Update model and show race result on scoreboard."""
        secs = self.result_report()
        self.timerwin = False
        tp = 'Time:'
        if self.start is not None and self.finish is None:
            self.finish = tod.now()
            if self.lstart is not None:
                self.start = self.lstart  # override with localtime
            self.set_elapsed()
        if self.timetype == '200m':
            tp = '200m:'
            # previously, winner was displayed on gemini here
        ts = None
        if self.start is not None and self.finish is not None:
            ts = (self.finish - self.start).timestr(2)
        if self.doscbplaces:
            fmt = ((3, 'l'), (3, 'r'), ' ', (self.meet.scb.linelen - 12, 'l'),
                   (5, 'r'))
            self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                               head=self.meet.racenamecat(
                                                   self.event),
                                               subhead=self.resulttype,
                                               coldesc=fmt,
                                               rows=self.results,
                                               timepfx=tp,
                                               timestr=ts)
            self.meet.scbwin.reset()
            self.doscbplaces = False
        self.setfinished()
        self._eliminated = None  # superfluous?
        self.resend_current()

    def do_startlist(self):
        """Show start list on scoreboard."""

        self.reorder_riders()
        self.meet.scbwin = None
        self.timerwin = False
        startlist = []
        name_w = self.meet.scb.linelen - 9
        for r in self.riders:
            if r[COL_INRACE]:
                name, club, nfo = self._getname(r[COL_NO], width=name_w)
                if len(club) != 3:
                    club = ''
                if r[COL_INFO]:
                    nfo = r[COL_INFO]
                if not nfo:
                    nfo = club
                startlist.append((r[COL_NO], name, nfo))
        fmt = ((3, 'r'), ' ', (name_w, 'l'), (5, 'r'))
        self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                           head=self.meet.racenamecat(
                                               self.event),
                                           subhead='STARTLIST',
                                           coldesc=fmt,
                                           rows=startlist)
        self.meet.scbwin.reset()
        self.resend_current()

    def resend_current(self):
        # TEMP issue cleared current
        fragment = self.event.get_fragment()
        if fragment:
            data = self.data_pack()
            if self.evtype == 'elimination':
                data['noLaps'] = True
            self.meet.db.sendCurrent(self.event, fragment, data)

    def data_pack(self):
        """Pack standard values for a current object"""
        ret = {}
        ret['competitionType'] = 'bunch'  # for all generic races
        ret['status'] = self._status
        ret['remain'] = self._remain
        ret['eliminated'] = self._eliminated
        ret['weather'] = self._weather
        if self._startlines is not None:
            ret['competitors'] = self._startlines
        if self._reslines is not None:
            ret['lines'] = self._reslines
        if self.finish is not None:
            if self.start is not None:
                ret['startTime'] = self.start
                ret['endTime'] = self.finish
        elif self.lstart is not None:
            ret['startTime'] = self.lstart
        if len(self.decisions) > 0:
            ret['decisions'] = self.meet.decision_list(self.decisions)
        return ret

    def stat_but_cb(self, button):
        """Race ctrl button callback."""
        if self.timerstat in ('idle', 'armstart'):
            self.armstart()
        elif self.timerstat in ('running', 'armfinish'):
            self.armfinish()

    def checkplaces(self, places=''):
        """Check the proposed places against current race model."""
        ret = True
        placeset = set()
        for no in strops.reformat_biblist(places).split():
            # repetition? - already in place set?
            if no in placeset:
                _log.error('Duplicate no in places: %r', no)
                ret = False
            placeset.add(no)
            # rider in the model?
            lr = self._getrider(no)
            if lr is None:
                if not self.meet.get_clubmode():
                    _log.error('Non-starter in places: %r', no)
                    ret = False
                # otherwise club mode allows non-starter in places
            else:
                # rider still in the race?
                if not lr[COL_INRACE]:
                    _log.error('DNF rider in places: %r', no)
                    ret = False
        return ret

    def race_ctrl_places_activate_cb(self, entry, data=None):
        """Respond to activate on place entry."""
        places = strops.reformat_placelist(entry.get_text())
        if self.checkplaces(places):
            self.places = places
            _log.debug('Event %r places updated: %r', self.evno, self.places)
            entry.set_text(self.places)
            self.do_places()  # triggers recalculate
            GLib.idle_add(self.delayed_announce)
            self.meet.delayed_export()
        else:
            _log.error('Places not updated')

    def race_ctrl_action_activate_cb(self, entry, data=None):
        """Perform current action on bibs listed."""
        rlist = entry.get_text()
        acode = self.action_model.get_value(
            self.ctrl_action_combo.get_active_iter(), 1)
        if acode == 'abd':
            self.dnfriders(strops.reformat_biblist(rlist), 'abd')
            entry.set_text('')
        elif acode == 'dns':
            self.dnfriders(strops.reformat_biblist(rlist), 'dns')
            entry.set_text('')
        elif acode == 'dnf':
            self.dnfriders(strops.reformat_biblist(rlist), 'dnf')
            entry.set_text('')
        elif acode == 'dsq':
            self.dnfriders(strops.reformat_biblist(rlist), 'dsq')
            entry.set_text('')
        elif acode == 'add':
            rlist = strops.riderlist_split(rlist, self.meet.rdb, self.series)
            for bib in rlist:
                self.addrider(bib)
            entry.set_text('')
        elif acode == 'del':
            dlist = strops.riderlist_split(rlist, self.meet.rdb, self.series)
            for bib in dlist:
                self.delrider(bib)
            entry.set_text('')
        elif acode == 'out':
            bib = rlist.strip().upper()
            if self.eliminate(bib):
                entry.set_text('')
            # Short-circuit method to avoid re-announce
            return False
        elif acode == 'in':
            bib = rlist.strip()
            if self.uneliminate(bib):
                entry.set_text('')
            # Short-circuit method to avoid re-announce
            return False
        else:
            _log.error('Ignoring invalid action')
            return False
        GLib.idle_add(self.delayed_announce)

    def update_expander_lbl_cb(self):
        """Update race info expander label."""
        self.info_expand.set_label(self.meet.infoline(self.event))

    def uneliminate(self, bib):
        """Remove rider from the set of eliminated riders."""
        ret = False
        r = self._getrider(bib)
        if r is not None:
            if r[COL_INRACE]:
                if bib in self.eliminated:
                    self.eliminated.remove(bib)
                    self.placexfer()
                    _log.info('Rider %r removed from eliminated riders', bib)
                    GLib.idle_add(self.delayed_announce)
                    ret = True
                else:
                    _log.error('Rider %r not eliminated', bib)
            else:
                _log.error('Cannot un-eliminate dnf rider: %r', bib)
        else:
            _log.error('Cannot un-eliminate non-starter: %r', bib)

        self.resend_current()
        return ret

    def eliminate(self, bib):
        """Register rider as eliminated."""
        bib = bib.upper()
        ret = False
        r = self._getrider(bib)
        if r is not None:
            if r[COL_INRACE]:
                if bib not in self.eliminated:
                    # ensure event is started
                    if self.start is None:
                        self.timerstat = 'armstart'
                        # allow a ~two lap start
                        st = tod.now() - tod.mktod(40)
                        self.starttrig(st, wallstart=st)
                    self.eliminated.append(bib)
                    self.placexfer()
                    _log.info('Rider %r out', bib)
                    ret = True
                    if self.evtype == 'elimination':
                        rno = r[COL_NO]
                        name, club, nfo = self._getname(
                            r[COL_NO],
                            width=self.meet.scb.linelen - 3 - len(rno))
                        resname, nation = self._getresname(r[COL_NO])
                        rstr = (rno + ' ' + name)
                        self.meet.scbwin = scbwin.scbintsprint(
                            scb=self.meet.scb,
                            line1=self.meet.racenamecat(self.event),
                            line2='RIDER ELIMINATED',
                            coldesc=[' ', (self.meet.scb.linelen - 1, 'l')],
                            rows=[[rstr]])
                        self.meet.scbwin.reset()
                        self.meet.gemini.reset_fields()
                        self.meet.gemini.set_bib(bib)
                        self.meet.gemini.show_brt()
                        self.meet.cmd_announce('eliminated', bib)
                        rank = None
                        place = None
                        if self._remain is not None:  # filled by placexfer
                            rank = self._remain + 1
                            place = '%s.' % (rank, )
                        self._eliminated = {
                            'rank': rank,
                            'class': place,
                            'competitor': bib,
                            'nation': nation,
                            'name': resname,
                            'info': nfo,
                        }
                        # announce it:
                        nrstr = strops.truncpad(rstr, 60)
                        self.meet.txt_postxt(21, 0, 'Out: ' + nrstr)
                        GLib.timeout_add_seconds(15, self.delayed_result)
                    else:
                        GLib.idle_add(self.delayed_result)
                    self.meet.delayed_export()
                else:
                    _log.error('Rider %r already eliminated', bib)
            else:
                _log.error('Cannot eliminate dnf rider: %r', bib)
        else:
            _log.error('Cannot eliminate non-starter: %r', bib)

        self.resend_current()
        return ret

    def delayed_result(self):
        if self.ctrl_action.get_property('has-focus'):
            if isinstance(self.meet.scbwin, scbwin.scbintsprint):
                FMT = [(3, 'l'), (3, 'r'), ' ',
                       (self.meet.scb.linelen - 11, 'l'), (4, 'r')]
                self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                                   head=self.meet.racenamecat(
                                                       self.event),
                                                   subhead=self.resulttype,
                                                   coldesc=FMT,
                                                   rows=self.results)
                self.meet.scbwin.reset()
        self.meet.cmd_announce('eliminated', '')
        self._eliminated = None
        self.meet.gemini.clear()
        GLib.idle_add(self.delayed_announce)

    def editent_cb(self, entry, col):
        """Shared event entry update callback."""
        if col == 'pref':
            self.event['pref'] = entry.get_text()
        elif col == 'info':
            self.event['info'] = entry.get_text()

    def editinfo_cb(self, cell, path, new_text, col):
        """Info cell update callback."""
        if self.evtype == 'handicap':
            self.riders[path][COL_INFO] = strops.mark2mark(new_text.strip())
        else:
            self.riders[path][COL_INFO] = new_text.strip()

    def _editname_cb(self, cell, path, new_text, col):
        """Edit the rider name if possible."""
        old_text = self.riders[path][col]
        if old_text != new_text:
            self.riders[path][col] = new_text
            rNo = self.riders[path][COL_NO]
            dbr = self.meet.rdb.get_rider(rNo, self.series)
            if dbr is None:
                # Assume one is required
                self.meet.rdb.add_empty(rNo, self.series)
                dbr = self.meet.rdb.get_rider(rNo, self.series)
            _log.debug('Updating %s %s detail', dbr.get_label(), dbr.get_id())
            dbr.rename(new_text)

    def gotorow(self, i=None):
        """Select row for specified iterator."""
        if i is None:
            i = self.riders.get_iter_first()
        if i is not None:
            self.view.scroll_to_cell(self.riders.get_path(i))
            self.view.set_cursor_on_cell(self.riders.get_path(i))

    def inrace_cb(self, cell, path, col):
        """Toggle rider inrace flag."""

        # refuse to update placed rider
        if self.riders[path][COL_PLACE].isdigit():
            _log.info('Rider %s in places - ignored',
                      self.riders[path][COL_NO])
            self.riders[path][COL_INRACE] = True
            return

        # otherwise toggle and update
        self.riders[path][COL_INRACE] = not (self.riders[path][COL_INRACE])
        if self.riders[path][COL_INRACE]:
            self.riders[path][COL_DNFCODE] = ''  # Remove dnfcode
        else:
            self.riders[path][COL_DNFCODE] = 'dnf'  # Assume dnf
        self.recalculate()

    def starttrig(self, e, wallstart=None):
        """React to start trigger."""
        if self.timerstat == 'armstart':
            self.start = e
            if wallstart is not None:
                self.lstart = wallstart
            else:
                self.lstart = tod.now()
            self.setrunning()
            if self.timetype == '200m':
                if wallstart is None:
                    GLib.timeout_add_seconds(4, self.armfinish)
                else:
                    GLib.idle_add(self.armfinish)
            if self._weather is None:
                self._weather = self.meet.get_weather()

    def fintrig(self, e):
        """React to finish trigger."""
        if self.timerstat == 'armfinish':
            self.finish = e
            self.setfinished()
            self.set_elapsed()
            self.log_elapsed()
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                self.showtimer()
            GLib.idle_add(self.delayed_announce)

    def recover_start(self):
        """Recover missed start time"""
        if self.timerstat in ('idle', 'armstart'):
            rt = self.meet.recover_time(self.startchan)
            if rt is not None:
                # rt: (event, wallstart)
                _log.info('Recovered start time: %s', rt[0].rawtime(3))
                if self.timerstat == 'idle':
                    self.timerstat = 'armstart'
                self.meet.main_timer.dearm(self.startchan)
                self.meet.main_timer.dearm('C0')
                self.starttrig(rt[0], rt[1])
            else:
                _log.info('No recent start time to recover')
        else:
            _log.info('Unable to recover start')

    def timercb(self, e):
        """Handle a timer event."""
        chan = strops.chan2id(e.chan)
        if chan == self.startchan or chan == 0:
            _log.debug('Got a start impulse')
            self.starttrig(e)
        elif chan == self.finchan:
            _log.debug('Got a finish impulse')
            self.fintrig(e)
        return False

    def timeout(self):
        """Update scoreboard and respond to timing events."""
        if not self.winopen:
            return False
        if self.finish is None:
            self.set_elapsed()
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                self.meet.scbwin.settime(self.time_lbl.get_text())
        return True

    def race_info_time_edit_activate_cb(self, button):
        """Display race timing edit dialog."""
        sections = {
            'times': {
                'object': None,
                'title': 'times',
                'schema': {
                    'title': {
                        'prompt': 'Manually adjust event time',
                        'control': 'section',
                    },
                    'start': {
                        'prompt': 'Start:',
                        'hint': 'Event start time',
                        'type': 'tod',
                        'places': 4,
                        'control': 'short',
                        'nowbut': True,
                        'value': self.start,
                    },
                    'finish': {
                        'prompt': 'Finish:',
                        'hint': 'Event finish time',
                        'type': 'tod',
                        'places': 4,
                        'control': 'short',
                        'nowbut': True,
                        'value': self.finish,
                    },
                },
            },
        }
        res = uiutil.options_dlg(window=self.meet.window,
                                 title='Edit times',
                                 sections=sections)
        if res['times']['start'][0] or res['times']['finish'][0]:
            try:
                self.set_finish(res['times']['finish'][2])
                self.set_start(res['times']['start'][2])
                self.set_elapsed()
                if self.start is not None and self.finish is not None:
                    self.log_elapsed()
            except Exception as v:
                _log.error('Error updating times %s: %s', v.__class__.__name__,
                           v)
            GLib.idle_add(self.delayed_announce)
        else:
            _log.info('Edit race times cancelled')

    def result_gen(self):
        """Generator function to export a final result."""
        ft = None
        for r in self.riders:
            bib = r[COL_NO]
            rank = None
            info = ''
            if self.evtype in ('handicap', 'sprint'):
                # include handicap and previous win info
                info = r[COL_INFO].strip()
            if self.onestart:
                if r[COL_INRACE]:
                    if r[COL_PLACE]:
                        rank = int(r[COL_PLACE])
                else:
                    if not r[COL_DNFCODE]:
                        r[COL_DNFCODE] = 'dnf'  # patch any missing codes
                    rank = r[COL_DNFCODE]
            time = None
            if self.finish is not None and ft is None:
                time = (self.finish - self.start).rawtime(2)
                ft = True
            yield (bib, rank, time, info)

    def data_bridge(self):
        """Export data bridge fragments, startlists and results"""
        fragment = self.event.get_fragment()
        if fragment:
            data = self.data_pack()
            self.meet.db.updateFragment(self.event, fragment, data)

    def result_report(self, recurse=False):
        """Return a list of report sections containing the race result."""
        self.recalculate()
        ret = []
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)
        sec.nobreak = True
        sec.heading = self.event.get_info(showevno=True)
        sec.lines = []
        lapstring = strops.lapstring(self.event['laps'])
        substr = '\u3000'.join(
            (lapstring, self.event['distance'], self.event['rules'])).strip()
        self._reslines = []
        first = True
        fs = ''
        if self.finish is not None and self.start is not None:
            fs = (self.finish - self.start).rawtime(2)
        rcount = 0
        pcount = 0
        rtot = len(self.riders)  # hack until somethng better
        if self._remain:
            pcount = self._remain
        for r in self.riders:
            plstr = ''
            rcount += 1
            rno = r[COL_NO]
            rh = self.meet.rdb.get_rider(rno, self.series)
            rname = ''
            rnat = None
            pilot = None
            inf = ''
            if rh is not None:
                rname = rh.resname()
                rnat = rh['nation']
                inf = rh['class']
                pilot = self.meet.rdb.get_pilot_line(rh)

            if r[COL_INRACE]:
                if self.onestart and r[COL_PLACE] != '':
                    plstr = r[COL_PLACE]
                    if r[COL_PLACE].isdigit():
                        plstr += '.'
                        pcount = int(r[COL_PLACE])
                    else:
                        pcount += 1
            else:
                plstr = r[COL_DNFCODE]
                if r[COL_DNFCODE] in ('dns', 'dsq', 'abd'):
                    pcount = rtot + 1
                else:
                    pcount = rtot

            if r[COL_INFO]:
                if self.evtype not in ('keirin',
                                       'sprint') and not self.inomnium:
                    inf = r[COL_INFO]

            if plstr:  # don't emit a row for unplaced riders
                if not first:
                    sec.lines.append([plstr, rno, rname, inf, None, None])
                else:
                    sec.lines.append([plstr, rno, rname, inf, fs, None])
                    first = False
                if pilot:
                    sec.lines.append(pilot)
                # todo: members + badges
                pname = None
                if pilot:
                    pname = pilot[2]
                self._reslines.append({
                    'rank': pcount,
                    'class': plstr,
                    'competitor': rno,
                    'nation': rnat,
                    'name': rname,
                    'pilot': pname,
                    'info': inf,
                })

        subv = []
        if substr:
            subv.append(substr)
        if self.onestart:
            subv.append(self.standingstr())
        sec.subheading = '\u3000'.join(subv)

        ret.append(sec)

        if len(self.decisions) > 0:
            ret.append(self.meet.decision_section(self.decisions))
        return ret

    def standingstr(self, width=None):
        """Return an event status string for reports and scb."""
        ret = ''
        if self.onestart:
            ret = 'Standings'
            rcount = 0
            pcount = 0
            winner = False
            for r in self.riders:
                if not r[COL_INRACE]:
                    pcount += 1
                elif r[COL_PLACE] != '':
                    if r[COL_PLACE] == '1':
                        winner = True
                    pcount += 1
                rcount += 1
            if winner:
                if rcount > 0 and pcount < rcount:
                    ret = 'Provisional Result'
                else:
                    ret = 'Result'
        return ret

    def show(self):
        """Show race window."""
        self.frame.show()

    def hide(self):
        """Hide race window."""
        self.frame.hide()

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
        self.series = event['seri']
        self.configfile = meet.event_configfile(self.evno)
        self.results = []
        self.resulttype = 'RESULT'

        self.readonly = not ui
        rstr = ''
        if self.readonly:
            rstr = 'readonly '
        _log.debug('Init %sevent %s', rstr, self.evno)
        self.decisions = []
        self.eliminated = []
        self.places = ''
        self.onestart = False
        self.start = None
        self.lstart = None
        self.finish = None
        self.winopen = ui  # window 'open' on proper load- or consult edb
        self.timerwin = False
        self.timerstat = 'idle'
        self.distance = None
        self.units = 'laps'
        self.timetype = 'start/finish'
        self.inomnium = False
        self.seedsrc = None
        self.doscbplaces = True  # auto show result on scb
        self.reorderflag = 0
        self.startchan = 0
        self.finchan = 1
        self.finished = False
        self._winState = {}  # cache ui settings for headless load/save
        self._status = None
        self._weather = None
        self._startlines = None
        self._reslines = None
        self._remain = None
        self._eliminated = None
        self._prevlap = None

        self.riders = Gtk.ListStore(
            str,  # 0 bib
            str,  # 1 name
            str,  # 2 reserved
            str,  # 3 reserved
            str,  # 4 xtra info
            bool,  # 5 DNF/DNS
            str,  # 6 placing
            str)  # 7 dnfcode

        # start timer and show window
        if ui:
            b = uiutil.builder('race.ui')
            self.frame = b.get_object('race_vbox')

            # info pane
            self.info_expand = b.get_object('info_expand')
            b.get_object('race_info_evno').set_text(self.evno)
            self.showev = b.get_object('race_info_evno_show')
            self.prefix_ent = b.get_object('race_info_prefix')
            self.prefix_ent.connect('changed', self.editent_cb, 'pref')
            self.prefix_ent.set_text(self.event['pref'])
            self.info_ent = b.get_object('race_info_title')
            self.info_ent.connect('changed', self.editent_cb, 'info')
            self.info_ent.set_text(self.event['info'])

            self.time_lbl = b.get_object('race_info_time')
            self.time_lbl.modify_font(uiutil.MONOFONT)

            # ctrl pane
            self.stat_but = uiutil.statButton()
            self.stat_but.set_sensitive(True)
            b.get_object('race_ctrl_stat_but').add(self.stat_but)

            self.ctrl_places = b.get_object('race_ctrl_places')
            self.ctrl_action_combo = b.get_object('race_ctrl_action_combo')
            self.ctrl_action = b.get_object('race_ctrl_action')
            self.action_model = b.get_object('race_action_model')

            # riders pane
            t = Gtk.TreeView(self.riders)
            self.view = t
            t.set_reorderable(True)
            t.set_enable_search(False)
            t.set_rules_hint(True)

            # riders columns
            uiutil.mkviewcoltxt(t, 'No.', COL_NO, calign=1.0)
            uiutil.mkviewcoltxt(t,
                                'Name',
                                COL_NAME,
                                self._editname_cb,
                                expand=True)
            uiutil.mkviewcoltxt(t, 'Info', COL_INFO, self.editinfo_cb)
            uiutil.mkviewcolbool(t, 'In', COL_INRACE, self.inrace_cb)
            uiutil.mkviewcoltxt(t, 'Place', COL_PLACE, halign=0.5, calign=0.5)
            t.show()
            b.get_object('race_result_win').add(t)
            b.connect_signals(self)
