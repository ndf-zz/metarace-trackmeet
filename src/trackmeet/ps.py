# SPDX-License-Identifier: MIT
"""Point score, madison and omnium handler for trackmeet."""

import os
import gi
import logging

gi.require_version("GLib", "2.0")
from gi.repository import GLib

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

import metarace
from metarace import tod
from metarace import unt4
from metarace import strops
from metarace import report
from metarace import jsonconfig

from . import uiutil
from . import scbwin

# temporary
from functools import cmp_to_key

_log = logging.getLogger('ps')
_log.setLevel(logging.DEBUG)

# config version string
EVENT_ID = 'ps-2.1'

# Model columns
SPRINT_COL_ID = 0
SPRINT_COL_LABEL = 1
SPRINT_COL_200 = 2
SPRINT_COL_SPLIT = 3
SPRINT_COL_PLACES = 4
SPRINT_COL_POINTS = 5

RES_COL_BIB = 0
RES_COL_FIRST = 1
RES_COL_LAST = 2
RES_COL_CLUB = 3
RES_COL_INRACE = 4
RES_COL_POINTS = 5
RES_COL_LAPS = 6
RES_COL_TOTAL = 7
RES_COL_PLACE = 8
RES_COL_FINAL = 9
RES_COL_INFO = 10
RES_COL_STPTS = 11

# scb consts

SPRINT_PLACE_DELAY = 3  # 3 seconds per place
SPRINT_PLACE_DELAY_MAX = 11  # to a maximum of 11

# scb function key mappings
key_startlist = 'F3'
key_results = 'F4'

# timing function key mappings
key_armstart = 'F5'
key_showtimer = 'F6'
key_armfinish = 'F9'
key_lapdown = 'F11'

# extended function key mappings
key_abort = 'F5'
key_falsestart = 'F6'


# temporary
def cmp(x, y):
    if x < y:
        return -1
    elif x > y:
        return 1
    else:
        return 0


class ps:
    """Data handling for point score omnium and Madison races."""

    def ridercb(self, rider):
        """Rider change notification function"""
        pass

    def eventcb(self, event):
        """Event change notification function"""
        pass

    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        self.sprints.clear()
        self.sprintpoints = {}
        definomnium = False
        defsprintlaps = ''
        defscoretype = 'points'
        defmasterslaps = 'No'
        if self.evtype == 'madison':
            defscoretype = 'madison'
            defmasterslaps = 'No'
        elif self.evtype == 'omnium':
            definomnium = True
            defsprintlaps = 'scr tmp elm'
            self.laplabels = {
                'scr': 'Scratch',
                'tmp': 'Tempo',
                'elm': 'Elimination'
            }
            self.sprintpoints = {
                'scr':
                '40 38 36 34 32 30 28 26 24 22 20 18 16 14 12 10 8 6 4 2 1 1 1 1 1 1',
                'tmp':
                '40 38 36 34 32 30 28 26 24 22 20 18 16 14 12 10 8 6 4 2 1 1 1 1 1 1',
                'elm':
                '40 38 36 34 32 30 28 26 24 22 20 18 16 14 12 10 8 6 4 2 1 1 1 1 1 1',
            }

        cr = jsonconfig.config({
            'event': {
                'startlist': '',
                'id': EVENT_ID,
                'start': None,
                'lstart': None,
                'finish': None,
                'comments': [],
                'sprintlaps': defsprintlaps,
                'distance': '',
                'runlap': '',
                'distunits': 'laps',
                'masterslaps': defmasterslaps,
                'inomnium': definomnium,
                'showinfo': True,
                'autospec': '',
                'scoring': defscoretype
            }
        })
        cr.add_section('event')
        cr.add_section('sprintplaces')
        cr.add_section('sprintpoints')
        cr.add_section('sprintsource')
        cr.add_section('laplabels')
        cr.add_section('points')
        if os.path.exists(self.configfile):
            try:
                with open(self.configfile, 'rb') as f:
                    cr.read(f)
            except Exception as e:
                _log.error('Unable to read config: %s', e)
        else:
            _log.info('%r not found, loading defaults', self.configfile)
        self.inomnium = cr.get_bool('event', 'inomnium')
        if self.inomnium:
            self.seedsrc = 1  # fetch start list seeding from omnium

        for r in cr.get('event', 'startlist').split():
            nr = [r, '', '', '', True, 0, 0, 0, '', -1, '', 0]
            if cr.has_option('points', r):
                ril = cr.get('points', r)
                if len(ril) >= 1:
                    nr[RES_COL_INRACE] = strops.confopt_bool(ril[0])
                if len(ril) >= 3:
                    try:
                        nr[RES_COL_LAPS] = int(ril[2])
                    except ValueError:
                        pass
                if len(ril) >= 4:
                    nr[RES_COL_INFO] = ril[3]
                if len(ril) >= 5:
                    spts = ril[4]
                    if spts.isdigit():
                        nr[RES_COL_STPTS] = int(spts)

            dbr = self.meet.rdb.get_rider(r, self.series)
            if dbr is not None:
                nr[1] = dbr['first']
                nr[2] = dbr['last']
                nr[3] = dbr['org']
            self.riders.append(nr)
        if cr.get('event', 'scoring').lower() == 'madison':
            self.scoring = 'madison'
        else:
            self.scoring = 'points'
        self.type_lbl.set_text(self.scoring.capitalize())

        # race infos
        self.comments = cr.get('event', 'comments')

        self.autospec = cr.get('event', 'autospec')
        self.distance = strops.confopt_dist(cr.get('event', 'distance'))
        self.units = strops.confopt_distunits(cr.get('event', 'distunits'))
        self.runlap = cr.get_posint('event', 'runlap')
        self.masterslaps = cr.get_bool('event', 'masterslaps')
        # override laps from event listings
        if not self.onestart and self.event['laps']:
            self.units = 'laps'
            self.distance = strops.confopt_posint(self.event['laps'],
                                                  self.distance)

        self.reset_lappoints()
        slt = cr.get('event', 'sprintlaps')
        self.sprintlaps = strops.reformat_biblist(slt)

        # load any special purpose sprint points
        for sid in cr.options('sprintpoints'):
            self.sprintpoints[sid] = cr.get('sprintpoints', sid)

        # load lap labels
        for sid in cr.options('laplabels'):
            self.laplabels[sid] = cr.get('laplabels', sid)

        # load any autospec'd sprint results
        for sid in cr.options('sprintsource'):
            self.sprintsource[sid] = cr.get('sprintsource', sid)

        self.sprint_model_init()

        oft = 0
        for s in self.sprints:
            places = ''
            sid = s[SPRINT_COL_ID]
            if cr.has_option('sprintplaces', sid):
                sp = cr.get('sprintplaces', sid)
                #_log.debug(u'sprintplaces = %r', sp)
                places = strops.reformat_placelist(sp)
                if len(places) > 0:
                    oft += 1
            s[SPRINT_COL_PLACES] = places
            if cr.has_option('sprintplaces', sid + '_200'):
                s[SPRINT_COL_200] = tod.mktod(
                    cr.get('sprintplaces', sid + '_200'))
            if cr.has_option('sprintplaces', sid + '_split'):
                s[SPRINT_COL_SPLIT] = tod.mktod(
                    cr.get('sprintplaces', sid + '_split'))
        if oft > 0:
            if oft >= len(self.sprints):
                oft = len(self.sprints) - 1
            self.ctrl_place_combo.set_active(oft)
            self.onestart = True

        ## for omnium - look up the places from event links if present
        if self.inomnium:
            for s in self.sprints:
                sid = s[SPRINT_COL_ID]
                if sid in self.sprintsource:
                    splac = self.meet.autoplace_riders(self,
                                                       self.sprintsource[sid],
                                                       final=True)
                    _log.debug('Loaded %r places from event %r: %r', sid,
                               self.sprintsource[sid], splac)
                    if splac:
                        s[SPRINT_COL_PLACES] = splac
        self.recalculate()

        self.info_expand.set_expanded(cr.get_bool('event', 'showinfo'))
        self.set_start(cr.get('event', 'start'), cr.get('event', 'lstart'))
        self.set_finish(cr.get('event', 'finish'))
        self.set_elapsed()

        # after load, add auto if required
        if not self.onestart and self.autospec:
            _log.debug('Fetching starters using autospec=%r with seedsrc=%r',
                       self.autospec, self.seedsrc)
            self.meet.autostart_riders(self, self.autospec, self.seedsrc)

        # After load complete - check config and report.
        eid = cr.get('event', 'id')
        if eid and eid != EVENT_ID:
            _log.info('Event config mismatch: %r != %r', eid, EVENT_ID)

    def get_startlist(self):
        """Return a list of bibs in the rider model."""
        ret = []
        for r in self.riders:
            ret.append(r[RES_COL_BIB])
        return ' '.join(ret)

    def saveconfig(self):
        """Save race to disk."""
        if self.readonly:
            _log.error('Attempt to save readonly event')
            return
        cw = jsonconfig.config()
        cw.add_section('event')
        if self.start is not None:
            cw.set('event', 'start', self.start.rawtime())
        if self.lstart is not None:
            cw.set('event', 'lstart', self.lstart.rawtime())
        if self.finish is not None:
            cw.set('event', 'finish', self.finish.rawtime())
        cw.set('event', 'startlist', self.get_startlist())
        cw.set('event', 'showinfo', self.info_expand.get_expanded())
        cw.set('event', 'distance', self.distance)
        cw.set('event', 'distunits', self.units)
        cw.set('event', 'scoring', self.scoring)
        if self.runlap is not None:
            cw.set('event', 'runlap', self.runlap)
        cw.set('event', 'masterslaps', self.masterslaps)
        cw.set('event', 'autospec', self.autospec)
        cw.set('event', 'inomnium', self.inomnium)
        cw.set('event', 'sprintlaps', self.sprintlaps)
        cw.set('event', 'comments', self.comments)

        cw.add_section('sprintplaces')
        cw.add_section('sprintpoints')
        cw.add_section('sprintsource')
        cw.add_section('laplabels')
        for s in self.sprints:
            sid = s[SPRINT_COL_ID]
            cw.set('sprintplaces', sid, s[SPRINT_COL_PLACES])
            if s[SPRINT_COL_200] is not None:
                cw.set('sprintplaces', sid + '_200',
                       s[SPRINT_COL_200].rawtime())
            if s[SPRINT_COL_SPLIT] is not None:
                cw.set('sprintplaces', sid + '_split',
                       s[SPRINT_COL_SPLIT].rawtime())
            if s[SPRINT_COL_POINTS] is not None:
                cw.set('sprintpoints', sid,
                       ' '.join(map(str, s[SPRINT_COL_POINTS])))
            if sid in self.laplabels:
                cw.set('laplabels', sid, self.laplabels[sid])
            if sid in self.sprintsource:
                cw.set('sprintsource', sid, self.sprintsource[sid])

        # rider result section
        cw.add_section('points')
        for r in self.riders:
            slice = [
                r[RES_COL_INRACE],
                str(r[RES_COL_POINTS]),
                str(r[RES_COL_LAPS]),
                str(r[RES_COL_INFO]),
                str(r[RES_COL_STPTS])
            ]
            cw.set('points', r[RES_COL_BIB], slice)

        cw.set('event', 'id', EVENT_ID)
        _log.debug('Saving points config %r', self.configfile)
        with metarace.savefile(self.configfile) as f:
            cw.write(f)

    def result_gen(self):
        """Generator function to export a final result."""
        fl = None
        ll = None
        for r in self.riders:
            bib = r[RES_COL_BIB]
            rank = None
            info = None
            if r[RES_COL_TOTAL] == 0:
                info = '-'
            else:
                info = str(r[RES_COL_TOTAL])
            if self.onestart:
                if r[RES_COL_INRACE]:
                    if r[RES_COL_PLACE] is not None and r[RES_COL_PLACE] != '':
                        rank = int(r[RES_COL_PLACE])
                else:
                    if r[RES_COL_INFO] in ['dns', 'dsq']:
                        rank = r[RES_COL_INFO]
                    else:
                        if r[RES_COL_INFO].isdigit():
                            rank = int(r[RES_COL_INFO])
                        else:
                            rank = 'dnf'  # ps only handle did not finish

            if self.scoring == 'madison':
                laps = r[RES_COL_LAPS]
                if fl is None:
                    fl = laps  # anddetermine laps down
                if ll is not None:
                    down = fl - laps
                    if ll != laps:
                        yield [
                            '', ' ',
                            str(down) + ' Lap' + strops.plural(down) +
                            ' Behind', ''
                        ]
                ll = laps

            time = None
            yield [bib, rank, time, info]

    def result_report(self, recurse=False):
        """Return a list of report sections containing the race result."""
        self.recalculate()
        ret = []
        sec = report.section('result')
        sec.heading = 'Event ' + self.evno + ': ' + ' '.join(
            [self.event['pref'], self.event['info']]).strip()
        lapstring = strops.lapstring(self.event['laps'])
        substr = ' '.join([lapstring, self.event['dist'],
                           self.event['prog']]).strip()
        sec.units = 'Pts'
        fs = ''
        if self.finish is not None:
            fs = self.time_lbl.get_text().strip()
        fl = None
        ll = None
        for r in self.riders:
            rno = r[RES_COL_BIB]
            rh = self.meet.rdb.get_rider(rno, self.series)
            rname = ''
            if rh is not None:
                rname = rh.resname()
            plstr = ''
            rcat = None
            if self.event['cate']:
                if rname is not None and rh['cat']:
                    rcat = rh['cat']
            if self.inomnium:
                rcat = None
            if rh is not None and rh['ucicode']:
                rcat = rh['ucicode']  # overwrite by force
            if self.onestart and r[RES_COL_PLACE] is not None:
                plstr = r[RES_COL_PLACE]
                if r[RES_COL_PLACE].isdigit():
                    plstr += '.'
                elif r[RES_COL_INFO] in ['dns', 'dsq']:
                    plstr = r[RES_COL_INFO]
                elif r[RES_COL_INFO] and r[RES_COL_INFO].isdigit():
                    plstr = r[RES_COL_INFO] + '.'
                ptstr = ''
                if r[RES_COL_TOTAL] != 0 and r[RES_COL_INRACE]:
                    ptstr = str(r[RES_COL_TOTAL])
                finplace = ''
                if r[RES_COL_FINAL] >= 0:
                    finplace = str(r[RES_COL_FINAL] + 1)

                if self.scoring == 'madison':
                    laps = r[RES_COL_LAPS]
                    if fl is None:
                        fl = laps  # anddetermine laps down
                    if ll is not None:
                        down = fl - laps
                        if ll != laps:
                            sec.lines.append([
                                None, None,
                                str(down) + ' Lap' + strops.plural(down) +
                                ' Behind', None, None, None
                            ])
                    ll = laps
                if plstr or finplace or ptstr:  # only output those with points
                    # dnf  or
                    # placed in final sprint
                    sec.lines.append([plstr, rno, rname, rcat, fs, ptstr])
                    ## TEAM HACKS
                    if 't' in self.series and rh is not None:
                        for trno in rh['note'].split():
                            trh = self.meet.rdb.get_rider(trno, self.series)
                            if trh is not None:
                                trname = trh.resname()
                                trinf = trh['ucicode']
                                sec.lines.append([
                                    None, '', trname, trinf, None, None, None
                                ])
                fs = ''

        if self.onestart:
            sec.subheading = substr + ' - ' + self.standingstr()
        else:
            if substr:
                sec.subheading = substr

        ret.append(sec)

        if len(self.comments) > 0:
            sec = report.bullet_text('decisions')
            sec.subheading = 'Decisions of the commisaires panel'
            for c in self.comments:
                sec.lines.append([None, c])
            ret.append(sec)

        # output intermediate sprints?

        return ret

    def getrider(self, bib):
        """Return temporary reference to model row."""
        ret = None
        for r in self.riders:
            if r[RES_COL_BIB] == bib:
                ret = r
                break
        return ret

    def getiter(self, bib):
        """Return temporary iterator to model row."""
        i = self.riders.get_iter_first()
        while i is not None:
            if self.riders.get_value(i, RES_COL_BIB) == bib:
                break
            i = self.riders.iter_next(i)
        return i

    def addrider(self, bib='', info=None):
        """Add specified rider to race model."""
        nr = [bib, '', '', '', True, 0, 0, 0, '', -1, '', 0]
        er = self.getrider(bib)
        if bib == '' or er is None:
            dbr = self.meet.rdb.get_rider(bib, self.series)
            if dbr is not None:
                nr[1] = dbr['first']
                nr[2] = dbr['last']
                nr[3] = dbr['org']
                if self.inomnium:
                    if info:
                        nr[RES_COL_INFO] = str(info)
            return self.riders.append(nr)
        else:
            if er is not None:
                #_log.debug('onestart is: %r', self.onestart)
                if self.inomnium and not self.onestart:
                    er[RES_COL_INFO] = str(info)
            return None

    def delrider(self, bib):
        """Remove the specified rider from the model."""
        i = self.getiter(bib)
        if i is not None:
            self.riders.remove(i)

    def resettimer(self):
        """Reset race timer."""
        self.set_finish()
        self.set_start()
        self.timerstat = 'idle'
        self.meet.main_timer.dearm(0)
        self.meet.main_timer.dearm(1)
        self.stat_but.update('idle', 'Idle')
        self.stat_but.set_sensitive(True)
        self.set_elapsed()

    def armstart(self):
        """Toggle timer arm start state."""
        if self.timerstat == 'idle':
            self.timerstat = 'armstart'
            self.stat_but.update('activity', 'Arm Start')
            self.meet.main_timer.arm(0)
        elif self.timerstat == 'armstart':
            self.timerstat = 'idle'
            self.stat_but.update('idle', 'Idle')
            self.meet.main_timer.dearm(0)
            self.curtimerstr = ''
        elif self.timerstat == 'running':
            self.timerstat = 'armsprintstart'
            self.stat_but.update('activity', 'Arm Sprint')
            self.meet.main_timer.arm(0)
        elif self.timerstat == 'armsprintstart':
            self.timerstat = 'running'
            self.stat_but.update('ok', 'Running')
            self.meet.main_timer.dearm(0)

    def armfinish(self):
        """Toggle timer arm finish state."""
        if self.timerstat in ['running', 'armsprint', 'armsprintstart']:
            self.timerstat = 'armfinish'
            self.stat_but.update('error', 'Arm Finish')
            self.meet.main_timer.arm(1)
        elif self.timerstat == 'armfinish':
            self.timerstat = 'running'
            self.stat_but.update('ok', 'Running')
            self.meet.main_timer.dearm(1)

    def sort_handicap(self, x, y):
        """Sort by ranking, then info, then riderno"""
        if x[3] == y[3]:
            if x[2] != y[2]:
                if x[2] is None:  # y sorts first
                    return 1
                elif y[2] is None:  # x sorts first
                    return -1
                else:  # Both should be ints here
                    return cmp(x[2], y[2])
            else:  # Defer to rider number
                if x[1].isdigit() and y[1].isdigit():
                    return cmp(int(x[1]), int(y[1]))
                else:
                    return cmp(x[1], y[1])
        else:
            return cmp(x[3], y[3])

    def reorder_riderno(self):
        """Sort the rider list by rider number."""
        if len(self.riders) > 1:
            auxmap = []
            cnt = 0
            intmark = 0
            for r in self.riders:
                rno = r[RES_COL_BIB]
                seed = strops.confopt_posint(r[RES_COL_INFO], 9999)
                rank = 0
                if self.inomnium and self.evtype == 'omnium':
                    # extract rank from current standing
                    if r[RES_COL_PLACE].isdigit() or r[RES_COL_PLACE] == '':
                        # but only add riders currently ranked, or unplaced
                        rank = strops.confopt_posint(r[RES_COL_PLACE], 9998)
                    else:
                        rank = 9999
                auxmap.append([cnt, rno, seed, rank])
                cnt += 1
            auxmap.sort(key=cmp_to_key(self.sort_handicap))
            #_log.debug('auxmap looks like: %r', auxmap)
            self.riders.reorder([a[0] for a in auxmap])

    def startlist_report(self, program=False):
        """Return a startlist report."""
        ret = []
        sec = report.twocol_startlist('startlist')
        if self.evtype == 'madison':
            # use the team singlecol method
            sec = report.section('startlist')
        headvec = [
            'Event', self.evno, ':', self.event['pref'], self.event['info']
        ]
        if not program:
            headvec.append('- Start List')
        sec.heading = ' '.join(headvec)
        lapstring = strops.lapstring(self.event['laps'])
        substr = ' '.join([lapstring, self.event['dist'],
                           self.event['prog']]).strip()
        if substr:
            sec.subheading = substr
        self.reorder_riderno()
        sec.lines = []
        col2 = []
        cnt = 0
        if self.inomnium and len(self.riders) > 0:
            pass
            #sec.lines.append([' ', ' ', 'The Fence', None, None, None])
            #col2.append([' ', ' ', 'Sprinters Lane', None, None, None])
        for r in self.riders:
            rno = r[RES_COL_BIB]
            rh = self.meet.rdb.get_rider(rno, self.series)
            inf = r[RES_COL_INFO]
            if self.inomnium:
                # inf holds seed, ignore for now
                inf = None
            # layout needs adhjustment
            #if rh[u'ucicode']:
            #inf = rh[u'ucicode']   # overwrite by force
            rname = ''
            if rh is not None:
                rname = rh.resname()

            if self.inomnium:
                if r[RES_COL_PLACE].isdigit() or r[RES_COL_PLACE] == '':
                    cnt += 1
                    if cnt % 2 == 1:
                        sec.lines.append([None, rno, rname, inf, None, None])
                    else:
                        col2.append([None, rno, rname, inf, None, None])
            else:
                cnt += 1
                sec.lines.append([None, rno, rname, inf, None, None])
                if self.evtype == 'madison':
                    # add the black/red entry
                    if rh is not None:
                        tvec = rh['note'].split()
                        if len(tvec) == 2:
                            trname = ''
                            trinf = ''
                            trh = self.meet.rdb.get_rider(tvec[0], self.series)
                            if trh is not None:
                                trname = trh.resname()
                                trinf = trh['ucicode']
                            sec.lines.append(
                                [None, 'Red', trname, trinf, None, None, None])
                            trname = ''
                            trinf = ''
                            trh = self.meet.rdb.get_rider(tvec[1], self.series)
                            if trh is not None:
                                trname = trh.resname()
                                trinf = trh['ucicode']
                            sec.lines.append([
                                None, 'Black', trname, trinf, None, None, None
                            ])
                            #sec.lines.append([None, None, None, None,
                            #None, None, None])

        for i in col2:
            sec.lines.append(i)

        # placeholders - why was this suppressed?
        if self.event['plac']:
            while cnt < self.event['plac']:
                sec.lines.append([None, None, None, None, None, None])
                cnt += 1

        fvec = []
        ptype = 'Riders'
        if self.evtype == 'madison':
            ptype = 'Teams'
        if cnt > 2:
            fvec.append('Total %s: %d' % (ptype, cnt))
        if self.event['reco']:
            fvec.append(self.event['reco'])

        if fvec:
            sec.footer = '\u2003'.join(fvec)

        ret.append(sec)
        return ret

    def do_startlist(self):
        """Show startlist on scoreboard."""
        self.reorder_riderno()
        self.meet.scbwin = None
        self.timerwin = False
        startlist = []
        name_w = self.meet.scb.linelen - 8
        for r in self.riders:
            if r[RES_COL_INRACE]:
                nfo = r[RES_COL_CLUB]
                if self.inomnium:
                    if self.evtype == 'omnium':
                        # this is the omnium aggregate, use standings for nfo
                        nfo = r[RES_COL_PLACE]
                    else:
                        # overwrite nfo with seed value
                        nfo = r[RES_COL_INFO]
                else:
                    if len(nfo) > 3:
                        nfo = nfo[0:3]
                        ## look it up?
                        #if self.series in self.meet.ridermap:
                        #rh = self.meet.ridermap[self.series][
                        #r[RES_COL_BIB]]
                        #if rh is not None:
                        #nfo = rh['note']
                startlist.append([
                    r[RES_COL_BIB],
                    strops.fitname(r[RES_COL_FIRST], r[RES_COL_LAST], name_w),
                    nfo
                ])
        FMT = [(3, 'r'), ' ', (name_w, 'l'), ' ', (3, 'r')]
        self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                           head=self.meet.racenamecat(
                                               self.event),
                                           subhead='STARTLIST',
                                           coldesc=FMT,
                                           rows=startlist)
        self.meet.scbwin.reset()

    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == Gdk.EventType.KEY_PRESS:
            key = Gdk.keyval_name(event.keyval) or 'None'
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                if key == key_abort:  # override ctrl+f5
                    self.resettimer()
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
                    self.recalculate()
                    self.do_places()
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_lapdown:
                    if self.runlap is not None and self.runlap > 0:
                        self.runlap -= 1
                    return True
        return False

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        if self.winopen:
            self.meet.txt_clear()
            self.meet.txt_title(' '.join([
                self.meet.event_string(self.evno), ':', self.event['pref'],
                self.event['info']
            ]))

            self.meet.txt_line(1, '_')
            self.meet.txt_line(8, '_')

            # fill in a sprint if not empty
            sid = None
            i = self.ctrl_place_combo.get_active_iter()
            if i is not None:
                pl = self.sprints.get_value(i, SPRINT_COL_PLACES)
                if pl is not None and pl != '':
                    sinfo = self.sprints.get_value(i, SPRINT_COL_LABEL)
                    self.meet.txt_setline(3, sinfo + ':')
                    sid = int(self.sprints.get_string_from_iter(i))
                    cnt = 0
                    unitshown = False
                    for r in self.sprintresults[sid]:
                        pstr = ''
                        if r[3] != '':
                            pstr = r[3]
                            if not unitshown:
                                pstr += 'pts'
                                unitshown = True
                        self.meet.txt_postxt(
                            4 + cnt, 0, ' '.join([
                                strops.truncpad(r[0], 3),
                                strops.truncpad(r[1], 3, 'r'),
                                strops.truncpad(r[2], 20), pstr
                            ]))
                        cnt += 1
                        if cnt > 3:  # is this required?
                            break
                else:
                    sid = int(self.sprints.get_string_from_iter(i)) - 1

            tp = ''
            if self.start is not None and self.finish is not None:
                et = self.finish - self.start
                tp = 'Time: ' + et.timestr(2) + '    '
                dist = self.meet.get_distance(self.distance, self.units)
                if dist:
                    tp += 'Avg: ' + et.speedstr(dist)
            self.meet.txt_postxt(4, 40, tp)

            # do result standing
            mscount = len(self.sprints)
            if sid is not None:
                mscount = sid
            sidstart = mscount - 8
            if sidstart < 0:
                sidstart = 0
            elif sidstart > len(self.sprints) - 10:
                sidstart = len(self.sprints) - 10
            if self.scoring == 'madison':
                leaderboard = []
                rtype = 'Team '
                if self.evtype != 'madison':
                    rtype = 'Rider'
                hdr = '     # ' + rtype + '                 Lap Pt '
                nopts = ''
                scnt = 0
                for s in self.sprints:
                    if scnt >= sidstart and scnt < sidstart + 10:
                        hdr += strops.truncpad(s[SPRINT_COL_ID], 4, 'r')
                        nopts += '    '
                    scnt += 1
                hdr += ' Fin'
                self.meet.txt_setline(10, hdr)
                curline = 11
                ldrlap = None
                curlap = None
                for r in self.riders:
                    if ldrlap is None:
                        ldrlap = r[RES_COL_LAPS]
                        curlap = ldrlap
                    lapdwn = r[RES_COL_LAPS] - ldrlap
                    lapstr = '  '
                    if lapdwn != 0:
                        lapstr = strops.truncpad(str(lapdwn), 2, 'r')

                    psrc = '-'
                    if r[RES_COL_TOTAL] != 0:
                        psrc = str(r[RES_COL_TOTAL])
                    ptstr = strops.truncpad(psrc, 2, 'r')

                    placestr = '   '
                    if self.onestart and r[RES_COL_PLACE] != '':
                        placestr = strops.truncpad(r[RES_COL_PLACE] + '.', 3)
                    elif not r[RES_COL_INRACE]:
                        placestr = 'dnf'

                    spstr = ''
                    if r[RES_COL_BIB] in self.auxmap:
                        scnt = 0
                        for s in self.auxmap[r[RES_COL_BIB]]:
                            if scnt >= sidstart and scnt < sidstart + 10:
                                spstr += str(s).rjust(4)
                            scnt += 1
                    else:
                        spstr = nopts

                    finstr = 'u/p'
                    if r[RES_COL_FINAL] >= 0:
                        finstr = strops.truncpad(str(r[RES_COL_FINAL] + 1), 3,
                                                 'r')

                    bibstr = strops.truncpad(r[RES_COL_BIB], 2, 'r')

                    clubstr = ''
                    if r[RES_COL_CLUB] != '' and len(r[RES_COL_CLUB]) <= 3:
                        clubstr = ' (' + r[RES_COL_CLUB] + ')'
                    namestr = strops.truncpad(strops.fitname(r[RES_COL_FIRST],
                                                             r[RES_COL_LAST],
                                                             22 - len(clubstr),
                                                             trunc=True) +
                                              clubstr,
                                              22,
                                              ellipsis=False)

                    self.meet.txt_postxt(
                        curline, 0, ' '.join([
                            placestr, bibstr, namestr, lapstr, ptstr, spstr,
                            finstr
                        ]))
                    curline += 1
                    if r[RES_COL_INRACE]:
                        if curlap > r[RES_COL_LAPS]:
                            while curlap != r[RES_COL_LAPS]:
                                curlap -= 1
                                if curlap < -15:
                                    break
                                leaderboard.append('-')
                        leaderboard.append(r[RES_COL_BIB].rjust(2) +
                                           psrc.rjust(3))
                self.meet.cmd_announce('leaderboard',
                                       chr(unt4.US).join(leaderboard))
            else:
                # use scratch race style layout for up to 26 riders
                count = 0
                curline = 11
                posoft = 0
                leaderboard = []
                for r in self.riders:
                    count += 1
                    if count == 14:
                        curline = 11
                        posoft = 41

                    psrc = '-'
                    if r[RES_COL_TOTAL] != 0:
                        psrc = str(r[RES_COL_TOTAL])

                    ptstr = strops.truncpad(psrc, 3, 'r')
                    clubstr = ''
                    if r[RES_COL_CLUB] != '' and len(r[RES_COL_CLUB]) <= 3:
                        clubstr = ' (' + r[RES_COL_CLUB] + ')'
                    namestr = strops.truncpad(strops.fitname(r[RES_COL_FIRST],
                                                             r[RES_COL_LAST],
                                                             27 - len(clubstr),
                                                             trunc=True) +
                                              clubstr,
                                              27,
                                              ellipsis=False)
                    placestr = '   '
                    if self.onestart and r[RES_COL_PLACE] != '':
                        placestr = strops.truncpad(r[RES_COL_PLACE] + '.', 3)
                    elif not r[RES_COL_INRACE]:
                        placestr = 'dnf'
                    bibstr = strops.truncpad(r[RES_COL_BIB], 3, 'r')
                    self.meet.txt_postxt(
                        curline, posoft,
                        ' '.join([placestr, bibstr, namestr, ptstr]))
                    curline += 1

                    if self.inomnium and r[RES_COL_INRACE]:
                        leaderboard.append(r[RES_COL_BIB].rjust(2) +
                                           psrc.rjust(3))
                if posoft > 0:
                    self.meet.txt_postxt(
                        10, 0,
                        '      # Rider                       Pts        # Rider                       Pts'
                    )
                else:
                    self.meet.txt_postxt(
                        10, 0, '      # Rider                       Pts')

                self.meet.cmd_announce('leaderboard',
                                       chr(unt4.US[0]).join(leaderboard))
        return False

    def do_places(self):
        """Show race result on scoreboard."""

        thesec = self.result_report()
        placestype = 'Standings: '
        if len(thesec) > 0:
            if self.finished:
                placestype = 'Result: '
        resvec = []
        fmt = ''
        hdr = ''
        if self.scoring == 'madison':
            name_w = self.meet.scb.linelen - 8
            fmt = [(2, 'r'), ' ', (name_w, 'l'), (2, 'r'), (3, 'r')]
            # does this require special consideration?
            leaderboard = []
            hdr = ' # team' + ((self.meet.scb.linelen - 13) * ' ') + 'lap pt'
            llap = None  # leader's lap
            for r in self.riders:
                if r[RES_COL_INRACE]:
                    bstr = r[RES_COL_BIB]
                    if llap is None:
                        llap = r[RES_COL_LAPS]
                    lstr = str(r[RES_COL_LAPS] - llap)
                    if lstr == '0': lstr = ''
                    pstr = str(r[RES_COL_TOTAL])
                    if pstr == '0': pstr = '-'
                    resvec.append([
                        bstr,
                        strops.fitname('', r[RES_COL_LAST].upper(), name_w),
                        lstr, pstr
                    ])
        else:
            name_w = self.meet.scb.linelen - 10
            fmt = [(3, 'l'), (3, 'r'), ' ', (name_w, 'l'), (3, 'r')]
            #self.meet.scb.linelen - 3) + ' pt'
            if self.inomnium:
                name_w -= 1
                fmt = [(3, 'l'), (3, 'r'), ' ', (name_w, 'l'), (4, 'r')]
                #self.meet.scb.linelen - 3) + ' pt'
            #ldr = None
            for r in self.riders:
                if r[RES_COL_INRACE]:
                    plstr = r[RES_COL_PLACE] + '.'
                    bstr = r[RES_COL_BIB]
                    #if ldr is None and r[RES_COL_TOTAL] > 0:
                    #ldr = r[RES_COL_TOTAL]	# current leader
                    pstr = str(r[RES_COL_TOTAL])
                    #if self.inomnium and ldr is not None:
                    #pstr = '-' + str(ldr - r[RES_COL_TOTAL])
                    if pstr == '0': pstr = '-'
                    resvec.append([
                        plstr, bstr,
                        strops.fitname(r[RES_COL_FIRST], r[RES_COL_LAST],
                                       name_w), pstr
                    ])
            # cols are: rank, bib, name, pts
        hdr = self.meet.racenamecat(self.event)
        self.meet.scbwin = None
        self.timerwin = False
        evtstatus = self.standingstr(width=self.meet.scb.linelen).upper()
        #evtstatus=u'STANDINGS'
        #if self.finished:
        #evtstatus=u'RESULT'
        self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                           head=hdr,
                                           subhead=evtstatus,
                                           coldesc=fmt,
                                           rows=resvec)
        self.meet.scbwin.reset()
        return False

    def dnfriders(self, biblist=''):
        """Remove listed bibs from the race."""
        recalc = False
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[RES_COL_INRACE] = False
                recalc = True
                _log.info('Rider %r withdrawn', bib)
            else:
                _log.warning('Did not withdraw %r', bib)
        if recalc:
            self.recalculate()
            self.meet.delayed_export()
        return False

    def announce_packet(self, line, pos, txt):
        self.meet.txt_postxt(line, pos, txt)
        return False

    def gainlap(self, biblist=''):
        """Credit each rider listed in biblist with a lap on the field."""
        recalc = False
        rlines = []
        srlines = []
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[RES_COL_LAPS] += 1
                recalc = True
                _log.info('Rider %r gains a lap', bib)
                rlines.append(' '.join([
                    bib.rjust(3),
                    strops.fitname(r[RES_COL_FIRST],
                                   r[RES_COL_LAST],
                                   26,
                                   trunc=True)
                ]))
                srlines.append([
                    bib,
                    strops.fitname(r[RES_COL_FIRST], r[RES_COL_LAST], 20)
                ])
            else:
                _log.warning('Did not gain lap for %r', bib)
        if recalc:
            self.oktochangecombo = False
            self.recalculate()
            GLib.timeout_add_seconds(2, self.announce_packet, 3, 50,
                                     'Gaining a lap:')
            cnt = 1
            for line in rlines:
                GLib.timeout_add_seconds(2, self.announce_packet, 3 + cnt, 50,
                                         line)
                cnt += 1
                if cnt > 4:
                    break
            # and do it on the scoreboard too ?!
            self.meet.scbwin = scbwin.scbintsprint(
                self.meet.scb, self.meet.racenamecat(self.event),
                'Gaining a Lap'.upper(), [(3, 'r'), ' ',
                                          (self.meet.scb.linelen - 4, 'l')],
                srlines)
            self.meet.scbwin.reset()
            self.next_sprint_counter += 1
            delay = SPRINT_PLACE_DELAY * len(rlines) or 1
            if delay > SPRINT_PLACE_DELAY_MAX:
                delay = SPRINT_PLACE_DELAY_MAX
            GLib.timeout_add_seconds(delay, self.delayed_result)
            self.meet.delayed_export()
        return False

    def loselap(self, biblist=''):
        """Deduct a lap from each rider listed in biblist."""
        recalc = False
        rlines = []
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[RES_COL_LAPS] -= 1
                recalc = True
                _log.info('Rider %r loses a lap', bib)
                rlines.append(' '.join([
                    bib.rjust(3),
                    strops.fitname(r[RES_COL_FIRST],
                                   r[RES_COL_LAST],
                                   26,
                                   trunc=True)
                ]))
            else:
                _log.warning('Did not lose lap for %r', bib)
        if recalc:
            self.oktochangecombo = False
            self.recalculate()
            GLib.timeout_add_seconds(2, self.announce_packet, 3, 50,
                                     'Losing a lap:')
            cnt = 1
            for line in rlines:
                GLib.timeout_add_seconds(2, self.announce_packet, 3 + cnt, 50,
                                         line)
                cnt += 1
                if cnt > 4:
                    break
            self.meet.delayed_export()
        return False

    def showtimer(self):
        """Show race timer on scoreboard"""
        tp = 'Time:'
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
            elap = self.finish - self.start
            self.meet.scbwin.settime(elap.timestr(2))
            dist = self.meet.get_distance(self.distance, self.units)
            if dist:
                self.meet.scbwin.setavg(elap.speedstr(dist))
                self.meet.scbwin.update()
        else:
            self.meet.scbwin.reset()

    def shutdown(self, win=None, msg='Exiting'):
        """Terminate event object"""
        _log.debug('Event shutdown: %r', msg)
        if not self.readonly:
            self.saveconfig()
        self.winopen = False

    def starttrig(self, e):
        """React to start trigger."""
        if self.timerstat == 'armstart':
            if self.distance and self.units == 'laps':
                self.runlap = self.distance - 1
                _log.debug('SET RUNLAP: %r', self.runlap)
            self.set_start(e, tod.now())
        elif self.timerstat == 'armsprintstart':
            self.stat_but.update('activity', 'Arm Sprint')
            self.meet.main_timer.arm(1)
            self.timerstat = 'armsprint'
            self.sprintstart = e
            self.sprintlstart = tod.now()

    def fintrig(self, e):
        """React to finish trigger"""
        if self.timerstat == 'armfinish':
            self.set_finish(e)
            self.set_elapsed()
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                self.showtimer()
            self.log_elapsed()
            GLib.idle_add(self.delayed_announce)
        elif self.timerstat == 'armsprint':
            self.stat_but.update('ok', 'Running')
            self.timerstat = 'running'
            if self.sprintstart is not None:
                elap = (e - self.sprintstart).timestr(2)
                _log.info('200m: %s', elap)
                if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                    self.meet.scbwin.avgpfx = '200m:'
                    self.meet.scbwin.setavg(elap)
            self.sprintstart = None

    def timercb(self, e):
        """Handle a timer event"""
        chan = strops.chan2id(e.chan)
        if chan == 0:
            _log.debug('Start impulse %s', e.rawtime(3))
            self.starttrig(e)
        elif chan == 1:
            _log.debug('Finish impulse %s', e.rawtime(3))
            self.fintrig(e)
        return False

    def timeout(self):
        """Update scoreboard and respond to timing events"""
        if not self.winopen:
            return False
        if self.finish is None and self.start is not None:
            self.set_elapsed()
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                self.meet.scbwin.settime(self.time_lbl.get_text())
        return True

    def do_properties(self):
        """Run race properties dialog"""
        b = uiutil.builder('ps_properties.ui')
        dlg = b.get_object('properties')
        dlg.set_transient_for(self.meet.window)
        rle = b.get_object('race_laps_entry')
        rle.set_text(self.sprintlaps)
        if self.onestart:
            rle.set_sensitive(False)
        rsb = b.get_object('race_showbib_toggle')
        rsb.set_active(self.masterslaps)
        rt = b.get_object('race_score_type')
        if self.scoring == 'madison':
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
        as_e.set_text(self.autospec)

        response = dlg.run()
        if response == 1:  # id 1 set in glade for "Apply"
            _log.debug('Updating race properties')
            if not self.onestart:
                newlaps = strops.reformat_biblist(rle.get_text())
                if self.sprintlaps != newlaps:
                    self.sprintlaps = newlaps
                    _log.info('Reset sprint model')
                    self.sprint_model_init()
            self.masterslaps = rsb.get_active()
            if rt.get_active() == 0:
                self.scoring = 'madison'
            else:
                self.scoring = 'points'
            self.type_lbl.set_text(self.scoring.capitalize())
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

            # update auto startlist spec
            nspec = as_e.get_text()
            if nspec != self.autospec:
                self.autospec = nspec
                if not self.onestart:
                    if self.autospec:
                        self.meet.autostart_riders(self, self.autospec,
                                                   self.seedsrc)

            # xfer starters if not empty
            slist = strops.riderlist_split(
                b.get_object('race_starters_entry').get_text(), self.meet.rdb,
                self.series)
            for s in slist:
                self.addrider(s)

            # recalculate
            self.reset_lappoints()
            self.recalculate()
            GLib.idle_add(self.delayed_announce)
        else:
            _log.debug('Edit race properties cancelled')

        # if prefix is empty, grab input focus
        if not self.prefix_ent.get_text():
            self.prefix_ent.grab_focus()
        dlg.destroy()

    ## Race timing manipulations
    def set_start(self, start='', lstart=None):
        """Set the race start time."""
        if type(start) is tod.tod:
            self.start = start
            if lstart is not None:
                self.lstart = lstart
            else:
                self.lstart = self.start
        else:
            self.start = tod.mktod(start)
            if lstart is not None:
                self.lstart = tod.mktod(lstart)
            else:
                self.lstart = self.start
        if self.start is None:
            pass
        else:
            if self.finish is None:
                self.set_running()

    def set_finish(self, finish=''):
        """Set the race finish time."""
        if type(finish) is tod.tod:
            self.finish = finish
        else:
            self.finish = tod.mktod(finish)
        if self.finish is None:
            if self.start is not None:
                self.set_running()
        else:
            if self.start is None:
                self.set_start(tod.ZERO)
            self.set_finished()

    def set_elapsed(self):
        """Update elapsed race time."""
        if self.start is not None and self.finish is not None:
            et = self.finish - self.start
            self.time_lbl.set_text(et.timestr(2))
        elif self.start is not None:
            runtm = (tod.now() - self.lstart).timestr(1)
            self.time_lbl.set_text(runtm)

            if self.runlap is not None:
                if self.runlap != self.lastrunlap:
                    _log.debug('Runlap: %r', self.runlap)
                    self.lastrunlap = self.runlap

        elif self.timerstat == 'armstart':
            self.time_lbl.set_text(tod.tod(0).timestr(1))
            if self.runlap and self.runlap != self.lastrunlap:
                _log.debug('Runlap: %r', self.runlap)
                self.lastrunlap = self.runlap
        else:
            self.time_lbl.set_text('')

    def log_elapsed(self):
        """Log elapsed time on timy receipt"""
        self.meet.main_timer.printline(self.meet.racenamecat(self.event))
        self.meet.main_timer.printline('      ST: ' + self.start.timestr(4))
        self.meet.main_timer.printline('     FIN: ' + self.finish.timestr(4))
        self.meet.main_timer.printline('    TIME: ' +
                                       (self.finish - self.start).timestr(2))

    def set_running(self):
        """Set timer to running"""
        self.timerstat = 'running'
        self.stat_but.update('ok', 'Running')

    def set_finished(self):
        """Set timer to finished"""
        self.timerstat = 'finished'
        self.stat_but.update('idle', 'Finished')
        self.stat_but.set_sensitive(False)
        self.ctrl_places.grab_focus()

    def update_expander_lbl_cb(self):
        """Update the expander label"""
        self.info_expand.set_label('Race Info : ' +
                                   self.meet.racenamecat(self.event, 64))

    def ps_info_time_edit_clicked_cb(self, button, data=None):
        """Run the edit times dialog."""
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

    def ps_ctrl_place_combo_changed_cb(self, combo, data=None):
        """Handle sprint combo change."""
        self.oktochangecombo = False  # cancel delayed combo changer
        i = self.ctrl_place_combo.get_active_iter()
        if i is not None:
            self.ctrl_places.set_text(
                self.sprints.get_value(i, SPRINT_COL_PLACES) or '')
        else:
            self.ctrl_places.set_text('')
        self.ctrl_places.grab_focus()

    def standingstr(self, width=None):
        """Return an event status string for reports and scb."""
        ret = 'Standings'
        totsprints = 0
        lastsprint = None
        sprintid = None
        cur = 1
        for s in self.sprints:
            #_log.debug(u'cur: %r, val: %r', cur, s[SPRINT_COL_PLACES])
            if s[SPRINT_COL_PLACES]:
                lastsprint = cur
                sprintid = s[SPRINT_COL_ID]
            if s[SPRINT_COL_ID] not in self.laplabels:
                totsprints += 1
                cur += 1
        if lastsprint is not None:
            if lastsprint >= totsprints:
                ret = 'Result'
                # check for all places in final sprint?
                for r in self.riders:
                    if r[RES_COL_INRACE] and r[RES_COL_FINAL] < 0:
                        # not placed at finish
                        ret = 'Provisional Result'
                        break
            else:
                ret = 'Standings'
                if lastsprint:
                    if sprintid in self.laplabels:
                        ret += ' After ' + self.laplabels[sprintid]
                    elif totsprints > 0:
                        if width is not None and width < 25:
                            ret += ' - Sprint {0}/{1}'.format(
                                lastsprint, totsprints)
                        else:
                            ret += ' After Sprint {0} of {1}'.format(
                                lastsprint, totsprints)
                    else:
                        _log.debug('Total sprints was 0: %r / %r', lastsprint,
                                   totsprints)
        return ret

    def delayed_result(self):
        """Roll the places entry on to the next sprint"""
        if self.next_sprint_counter > 1:
            self.next_sprint_counter -= 1
        elif self.next_sprint_counter == 1:
            self.next_sprint_counter = 0
            self.do_places()
            if self.ctrl_places.get_property('has-focus'):
                if self.oktochangecombo:
                    i = self.ctrl_place_combo.get_active_iter()
                    i = self.ctrl_place_combo.get_model().iter_next(i)
                    if i is not None:
                        self.ctrl_place_combo.set_active_iter(i)
            else:
                # input widget lost focus, don't auto advance
                self.oktochangecombo = False
        else:
            self.next_sprint_counter = 0  # clamp negatives
        return False

    def checkplaces(self, places=''):
        """Check the proposed places against current race model"""
        ret = True
        placeset = set()
        for no in strops.reformat_biblist(places).split():
            # repetition? - already in place set?
            if no in placeset:
                _log.error('Duplicate no in places: %r', no)
                ret = False
            placeset.add(no)
            # rider in the model?
            lr = self.getrider(no)
            if lr is None:
                if not self.meet.get_clubmode():
                    _log.error('Non-starter in places: %r', no)
                    ret = False
                # otherwise club mode allows non-starter in places
            else:
                # rider still in the race?
                if not lr[RES_COL_INRACE]:
                    _log.error('DNF rider in places: %r', no)
                    ret = False
        return ret

    def ps_ctrl_places_activate_cb(self, entry, data=None):
        """Handle places entry"""
        places = strops.reformat_placelist(entry.get_text())
        if self.checkplaces(places):
            self.oktochangecombo = False  # cancel existing delayed change
            entry.set_text(places)

            i = self.ctrl_place_combo.get_active_iter()
            prevplaces = self.sprints.get_value(i, SPRINT_COL_PLACES)
            self.sprints.set_value(i, SPRINT_COL_PLACES, places)
            sid = int(self.sprints.get_string_from_iter(i))
            sinfo = self.sprints.get_value(i, SPRINT_COL_LABEL)
            self.recalculate()
            self.timerwin = False
            _log.info('%s: %r', sinfo, places)
            if prevplaces == '':
                FMT = [(2, 'l'), (3, 'r'), ' ',
                       (self.meet.scb.linelen - 8, 'l'), ' ', (1, 'r')]
                self.meet.scbwin = scbwin.scbintsprint(
                    self.meet.scb, self.meet.racenamecat(self.event),
                    sinfo.upper(), FMT, self.sprintresults[sid][0:4])
                self.meet.scbwin.reset()
                self.next_sprint_counter += 1
                delay = SPRINT_PLACE_DELAY * len(self.sprintresults[sid]) or 1
                if delay > SPRINT_PLACE_DELAY_MAX:
                    delay = SPRINT_PLACE_DELAY_MAX
                self.oktochangecombo = True
                GLib.timeout_add_seconds(delay, self.delayed_result)
            elif type(self.meet.scbwin) is scbwin.scbtable:
                self.do_places()  # overwrite result table?
            GLib.timeout_add_seconds(1, self.delayed_announce)
            self.meet.delayed_export()
        else:
            _log.error('Places not updated')

    def ps_ctrl_action_combo_changed_cb(self, combo, data=None):
        """Handle change on action combo."""
        self.ctrl_action.set_text('')
        self.ctrl_action.grab_focus()

    def ps_ctrl_action_activate_cb(self, entry, data=None):
        """Perform current action on bibs listed."""
        rlist = entry.get_text()
        acode = self.action_model.get_value(
            self.ctrl_action_combo.get_active_iter(), 1)
        if acode == 'gain':
            self.gainlap(strops.reformat_biblist(rlist))
            entry.set_text('')
        elif acode == 'lost':
            self.loselap(strops.reformat_biblist(rlist))
            entry.set_text('')
        elif acode == 'dnf':
            self.dnfriders(strops.reformat_biblist(rlist))
            entry.set_text('')
        elif acode == 'add':
            rlist = strops.riderlist_split(rlist, self.meet.rdb, self.series)
            for bib in rlist:
                self.addrider(bib)
            entry.set_text('')
        elif acode == 'del':
            rlist = strops.riderlist_split(rlist, self.meet.rdb, self.series)
            for bib in rlist:
                self.delrider(bib)
            entry.set_text('')
        elif acode == 'lap':
            self.runlap = strops.confopt_posint(rlist)
        else:
            _log.debug('Ignoring invalid action')
        GLib.idle_add(self.delayed_announce)

    def ps_sprint_cr_label_edited_cb(self, cr, path, new_text, data=None):
        """Sprint column edit"""
        self.sprints[path][SPRINT_COL_LABEL] = new_text

    def ps_sprint_cr_places_edited_cb(self, cr, path, new_text, data=None):
        """Sprint place edit"""
        new_text = strops.reformat_placelist(new_text)
        self.sprints[path][SPRINT_COL_PLACES] = new_text
        opath = self.sprints.get_string_from_iter(
            self.ctrl_place_combo.get_active_iter())
        if opath == path:
            self.ctrl_places.set_text(new_text)
        self.recalculate()
        # edit places outside control - no auto trigger of export

    def editcol_db(self, cell, path, new_text, col):
        """Cell update with writeback to meet"""
        new_text = new_text.strip()
        self.riders[path][col] = new_text.strip()
        GLib.idle_add(self.meet.rider_edit, self.riders[path][RES_COL_BIB],
                      self.series, col, new_text)

    def editcol_cb(self, cell, path, new_text, col):
        self.riders[path][col] = new_text.strip()

    def ps_result_cr_inrace_toggled_cb(self, cr, path, data=None):
        self.riders[path][RES_COL_INRACE] = not (
            self.riders[path][RES_COL_INRACE])
        self.recalculate()

    def ps_result_cr_laps_edited_cb(self, cr, path, new_text, data=None):
        try:
            laps = int(new_text)
            self.riders[path][RES_COL_LAPS] = laps
            self.recalculate()
        except ValueError:
            _log.warning('Ignoring non-numeric lap count')

    def zeropoints(self):
        for r in self.riders:
            r[RES_COL_POINTS] = 0
            r[RES_COL_TOTAL] = 0
            r[RES_COL_PLACE] = ''
            r[RES_COL_FINAL] = -1  # Negative => Unplaced in final sprint

    def pointsxfer(self, placestr, final=False, index=0, points=None):
        """Transfer points from sprint placings to aggregate."""
        placeset = set()
        if points is None:
            points = [5, 3, 2, 1]  # Default is four places
        self.sprintresults[index] = []
        place = 0
        count = 0
        name_w = self.meet.scb.linelen - 8
        for placegroup in placestr.split():
            for bib in placegroup.split('-'):
                if bib not in placeset:
                    placeset.add(bib)
                    r = self.getrider(bib)
                    if r is None:  # ensure rider exists at this point
                        _log.info('Adding non-starter: %r', bib)
                        self.addrider(bib)
                        r = self.getrider(bib)
                    ptsstr = ''
                    if place < len(points):
                        ptsstr = str(points[place])
                        r[RES_COL_POINTS] += points[place]
                        if bib not in self.auxmap:
                            self.auxmap[bib] = self.nopts[0:]
                        self.auxmap[bib][index] = str(points[place])
                    if final:
                        r[RES_COL_FINAL] = place
                        self.finished = True
                    plstr = str(place + 1) + '.'
                    fname = r[RES_COL_FIRST]
                    lname = r[RES_COL_LAST]
                    club = r[RES_COL_CLUB]
                    if len(club) > 3:
                        club = club[0:3]
                        ## look it up?
                        #if self.series in self.meet.ridermap:
                        #rh = self.meet.ridermap[self.series][bib]
                        #if rh is not None:
                        #club = rh[u'note']
                    self.sprintresults[index].append([
                        plstr, r[RES_COL_BIB],
                        strops.fitname(fname, lname, name_w), ptsstr,
                        strops.resname(fname, lname, club)
                    ])
                    count += 1
                else:
                    _log.error('Ignoring duplicate no: %r', bib)
            place = count
        if count > 0:
            self.onestart = True

    def retotal(self, r):
        """Update totals"""
        if self.scoring == 'madison':
            r[RES_COL_TOTAL] = r[RES_COL_STPTS] + r[RES_COL_POINTS]
        else:
            r[RES_COL_TOTAL] = r[RES_COL_STPTS] + r[RES_COL_POINTS] + (
                self.lappoints * r[RES_COL_LAPS])

    # Sorting performed in-place on aux table with cols:
    #  0 INDEX		Index in main model
    #  1 BIB		Rider's bib
    #  2 INRACE		Bool rider still in race?
    #  3 LAPS		Rider's laps up/down
    #  4 TOTAL		Total points scored
    #  5 FINAL		Rider's place in final sprint (-1 for unplaced)

    # Point score sorting:
    # inrace / points / final sprint
    def sortpoints(self, x, y):
        if x[2] != y[2]:  # compare inrace
            if x[2]:
                return -1
            else:
                return 1
        else:  # defer to points
            return self.sortpointsonly(x, y)

    def sortpointsonly(self, x, y):
        if x[6] == y[6]:
            if x[4] > y[4]:
                return -1
            elif x[4] < y[4]:
                return 1
            else:  # defer to last sprint
                if x[5] == y[5]:
                    #_log.warning('Sort could not split riders.')
                    return 0  # places same - or both unplaced
                else:
                    xp = x[5]
                    if xp < 0: xp = 9999
                    yp = y[5]
                    if yp < 0: yp = 9999
                    return cmp(xp, yp)
        else:
            return (cmp(x[6], y[6]))

    def sortmadison(self, x, y):
        """Lap-based points (old-style Madison)"""
        if x[2] != y[2]:  # compare inrace
            if x[2]:
                return -1
            else:
                return 1
        else:  # defer to distance (laps)
            if x[3] > y[3]:
                return -1
            elif x[3] < y[3]:
                return 1
            else:  # defer to points / final sprint
                return self.sortpointsonly(x, y)

    def sort_riderno(self, x, y):
        return cmp(strops.riderno_key(x[1]), strops.riderno_key(y[1]))

    # result recalculation
    def recalculate(self):
        self.zeropoints()
        self.finished = False
        self.auxmap = {}
        idx = 0
        for s in self.sprints:
            self.pointsxfer(s[SPRINT_COL_PLACES], s[SPRINT_COL_ID] == '0', idx,
                            s[SPRINT_COL_POINTS])
            idx += 1

        if len(self.riders) == 0:
            return

        auxtbl = []
        idx = 0
        for r in self.riders:
            ptotal = r[RES_COL_TOTAL]
            ranker = 0
            if not r[RES_COL_INRACE]:
                ptotal = 0
                if r[RES_COL_INFO] and r[RES_COL_INFO].isdigit():
                    ranker = int(r[RES_COL_INFO])
            self.retotal(r)
            auxtbl.append([
                idx, r[RES_COL_BIB], r[RES_COL_INRACE], r[RES_COL_LAPS],
                r[RES_COL_TOTAL], r[RES_COL_FINAL], ranker
            ])
            idx += 1
        if self.scoring == 'madison':
            auxtbl.sort(key=cmp_to_key(self.sortmadison))
        else:
            auxtbl.sort(key=cmp_to_key(self.sortpoints))
        self.riders.reorder([a[0] for a in auxtbl])
        place = 0
        idx = 0
        for r in self.riders:
            if r[RES_COL_INRACE]:
                if idx == 0:
                    place = 1
                else:
                    if self.scoring == 'madison':
                        if self.sortmadison(auxtbl[idx - 1], auxtbl[idx]) != 0:
                            place = idx + 1
                    else:
                        if self.sortpoints(auxtbl[idx - 1], auxtbl[idx]) != 0:
                            place = idx + 1
                r[RES_COL_PLACE] = str(place)
                idx += 1
            else:
                r[RES_COL_PLACE] = 'dnf'

    def sprint_model_init(self):
        """Initialise the sprint places model"""
        self.ctrl_place_combo.set_active(-1)
        self.ctrl_places.set_sensitive(False)
        self.sprints.clear()
        self.auxmap = {}
        self.nopts = []
        isone = False
        self.sprintresults = []
        for sl in self.sprintlaps.split():
            isone = True
            lt = sl
            if sl.isdigit():
                if int(sl) == 0:
                    lt = 'Final sprint'
                else:
                    lt = 'Sprint at ' + sl + ' to go'
            sp = None
            if sl in self.sprintpoints:
                nextp = []
                for nv in self.sprintpoints[sl].split():
                    if nv.isdigit():
                        nextp.append(int(nv))
                    else:
                        nextp = None
                        break
                sp = nextp
            nr = [sl, lt, None, None, '', sp]
            self.sprints.append(nr)
            self.sprintresults.append([])
            self.nopts.append('')
        if isone:
            self.ctrl_place_combo.set_active(0)
            self.ctrl_places.set_sensitive(True)

    def spptsedit(self, cr, path, new_text, data=None):
        """Sprint points edit"""
        new_text = strops.reformat_biblist(new_text)
        op = None
        nextp = []
        for nv in new_text.split():
            if nv.isdigit():
                nextp.append(int(nv))
            else:
                nextp = None
                break
        sid = self.sprints[path][SPRINT_COL_ID]
        if nextp is not None and len(nextp) > 0:
            self.sprintpoints[sid] = ' '.join(map(str, nextp))
            op = nextp
        else:
            if sid in self.sprintpoints:
                del self.sprintpoints[sid]
        self.sprints[path][SPRINT_COL_POINTS] = op
        self.recalculate()

    def spptsstr(self, col, cr, model, iter, data=None):
        """Format tod into text for listview"""
        pv = model.get_value(iter, SPRINT_COL_POINTS)
        if pv is not None and len(pv) > 0:
            cr.set_property('text', ', '.join(map(str, pv)))
        else:
            cr.set_property('text', '')

    def todstr(self, col, cr, model, iter, data=None):
        """Format tod into text for listview"""
        st = model.get_value(iter, SPRINT_COL_200)
        ft = model.get_value(iter, SPRINT_COL_SPLIT)
        if st is not None and ft is not None:
            cr.set_property('text', (ft - st).timestr(2))
        else:
            cr.set_property('text', '')

    def reset_lappoints(self):
        """Update lap points allocation"""
        if self.masterslaps:
            self.lappoints = 10
        else:
            self.lappoints = 20

    def destroy(self):
        """Signal race shutdown"""
        self.frame.destroy()

    def show(self):
        """Show race window"""
        self.frame.show()

    def hide(self):
        """Hide race window"""
        self.frame.hide()

    def editent_cb(self, entry, col):
        """Shared event entry update callback"""
        if col == 'pref':
            self.event['pref'] = entry.get_text()
        elif col == 'info':
            self.event['info'] = entry.get_text()
        self.update_expander_lbl_cb()

    def __init__(self, meet, event, ui=True):
        """Constructor"""
        self.meet = meet
        self.event = event
        self.evno = event['evid']
        self.evtype = event['type']
        self.series = event['seri']
        self.configfile = meet.event_configfile(self.evno)

        self.readonly = not ui
        rstr = ''
        if self.readonly:
            rstr = 'readonly '
        _log.debug('Init %sevent %s', rstr, self.evno)

        # race property attributes
        self.comments = []
        self.masterslaps = True
        self.lappoints = 20
        self.scoring = 'points'
        self.distance = None
        self.units = 'laps'
        self.sprintlaps = ''
        self.sprintpoints = {}
        self.nopts = []
        self.sprintresults = []
        self.laplabels = {}
        self.sprintsource = {}
        self.auxmap = {}

        # race run time attributes
        self.onestart = False
        self.runlap = None
        self.lastrunlap = None

        self.start = None
        self.lstart = None
        self.finish = None
        self.winopen = ui
        self.timerwin = False
        self.timerstat = 'idle'
        self.curtimerstr = ''
        self.sprintstart = None
        self.sprintlstart = None
        self.next_sprint_counter = 0
        self.oktochangecombo = False
        self.autospec = ''
        self.finished = False
        self.inomnium = False
        self.seedsrc = None

        # data models
        self.sprints = Gtk.ListStore(
            str,  # ID = 0
            str,  # LABEL = 1
            object,  # 200 = 2
            object,  # SPLITS = 3
            str,  # PLACES = 4
            object)  # POINTS = 5

        self.riders = Gtk.ListStore(
            str,  # BIB = 0
            str,  # FIRST = 1
            str,  # LAST = 2
            str,  # CLUB = 3
            bool,  # INRACE = 4
            int,  # POINTS = 5
            int,  # LAPS = 6
            int,  # TOTAL = 7
            str,  # PLACE = 8
            int,  # FINAL = 9
            str,  # INFO = 10
            int)  # STPTS = 11

        b = uiutil.builder('ps.ui')
        self.frame = b.get_object('ps_vbox')
        self.frame.connect('destroy', self.shutdown)

        # info pane
        self.info_expand = b.get_object('info_expand')
        b.get_object('ps_info_evno').set_text(self.evno)
        self.showev = b.get_object('ps_info_evno_show')
        self.prefix_ent = b.get_object('ps_info_prefix')
        self.prefix_ent.connect('changed', self.editent_cb, 'pref')
        self.prefix_ent.set_text(self.event['pref'])
        self.info_ent = b.get_object('ps_info_title')
        self.info_ent.connect('changed', self.editent_cb, 'info')
        self.info_ent.set_text(self.event['info'])

        self.time_lbl = b.get_object('ps_info_time')
        self.time_lbl.modify_font(uiutil.MONOFONT)
        self.update_expander_lbl_cb()
        self.type_lbl = b.get_object('race_type')
        self.type_lbl.set_text(self.scoring.capitalize())

        # ctrl pane
        self.stat_but = uiutil.statButton()
        self.stat_but.set_sensitive(True)
        b.get_object('ps_ctrl_stat_but').add(self.stat_but)

        self.ctrl_place_combo = b.get_object('ps_ctrl_place_combo')
        self.ctrl_place_combo.set_model(self.sprints)
        self.ctrl_places = b.get_object('ps_ctrl_places')
        self.ctrl_action_combo = b.get_object('ps_ctrl_action_combo')
        self.ctrl_action = b.get_object('ps_ctrl_action')
        self.action_model = b.get_object('ps_action_model')

        if ui:
            # sprints pane
            t = Gtk.TreeView(self.sprints)
            t.set_reorderable(True)
            t.set_enable_search(False)
            t.set_rules_hint(True)
            t.show()
            uiutil.mkviewcoltxt(t,
                                'Sprint',
                                SPRINT_COL_LABEL,
                                self.ps_sprint_cr_label_edited_cb,
                                expand=True)
            #uiutil.mkviewcoltod(t, u'200m', cb=self.todstr)
            uiutil.mkviewcoltxt(t,
                                'Places',
                                SPRINT_COL_PLACES,
                                self.ps_sprint_cr_places_edited_cb,
                                expand=True)
            uiutil.mkviewcoltod(t,
                                'Points',
                                cb=self.spptsstr,
                                editcb=self.spptsedit)
            b.get_object('ps_sprint_win').add(t)

            # results pane
            t = Gtk.TreeView(self.riders)
            t.set_reorderable(True)
            t.set_enable_search(False)
            t.set_rules_hint(True)
            t.show()
            uiutil.mkviewcoltxt(t, 'No.', RES_COL_BIB, calign=1.0)
            uiutil.mkviewcoltxt(t,
                                'First Name',
                                RES_COL_FIRST,
                                self.editcol_db,
                                expand=True)
            uiutil.mkviewcoltxt(t,
                                'Last Name',
                                RES_COL_LAST,
                                self.editcol_db,
                                expand=True)
            uiutil.mkviewcoltxt(t, 'Club', RES_COL_CLUB, self.editcol_db)
            uiutil.mkviewcoltxt(t, 'Info', RES_COL_INFO, self.editcol_cb)
            uiutil.mkviewcolbool(t,
                                 'In',
                                 RES_COL_INRACE,
                                 self.ps_result_cr_inrace_toggled_cb,
                                 width=50)
            uiutil.mkviewcoltxt(t, 'Pts', RES_COL_POINTS, calign=1.0, width=50)
            uiutil.mkviewcoltxt(t,
                                'Laps',
                                RES_COL_LAPS,
                                calign=1.0,
                                width=50,
                                cb=self.ps_result_cr_laps_edited_cb)
            uiutil.mkviewcoltxt(t,
                                'Total',
                                RES_COL_TOTAL,
                                calign=1.0,
                                width=50)
            uiutil.mkviewcoltxt(t, 'L/S', RES_COL_FINAL, calign=0.5, width=50)
            uiutil.mkviewcoltxt(t, 'Rank', RES_COL_PLACE, calign=0.5, width=50)
            b.get_object('ps_result_win').add(t)

            # connect signal handlers
            b.connect_signals(self)
