# SPDX-License-Identifier: MIT
"""Generic race handler for trackmeet."""

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
from metarace import strops
from metarace import report
from metarace import jsonconfig

from . import uiutil
from . import scbwin

# temporary
from functools import cmp_to_key

_log = logging.getLogger('race')
_log.setLevel(logging.DEBUG)

# config version string
EVENT_ID = 'race-2.1'

# race model column constants
COL_BIB = 0
COL_FIRSTNAME = 1
COL_LASTNAME = 2
COL_CLUB = 3
COL_INFO = 4
COL_DNF = 5
COL_PLACE = 6

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


# temporary
def cmp(x, y):
    if x < y:
        return -1
    elif x > y:
        return 1
    else:
        return 0


class race:
    """Data handling for scratch, handicap, keirin, derby, etc races."""

    def ridercb(self, rider):
        """Rider change notification function"""
        pass

    def eventcb(self, event):
        """Event change notification function"""
        pass

    def clearplaces(self):
        """Clear places from data model."""
        for r in self.riders:
            r[COL_PLACE] = ''

    def getrider(self, bib):
        """Return temporary reference to model row."""
        ret = None
        for r in self.riders:
            if r[COL_BIB] == bib:
                ret = r
                break
        return ret

    def getiter(self, bib):
        """Return temporary iterator to model row."""
        i = self.riders.get_iter_first()
        while i is not None:
            if self.riders.get_value(i, COL_BIB) == bib:
                break
            i = self.riders.iter_next(i)
        return i

    def delayed_reorder(self):
        """Call reorder if the flag is one."""
        if self.reorderflag > 1:
            self.reorderflag -= 1
        elif self.reorderflag == 1:
            self.reorder_handicap()
            self.reorderflag = 0
        else:
            self.reorderflag = 0  # clamp negatives
        return False

    def addrider(self, bib='', info=None):
        """Add specified rider to race model."""
        nr = [bib, '', '', '', '', False, '']
        er = self.getrider(bib)
        if not bib or er is None:
            dbr = self.meet.rdb.get_rider(bib, self.series)
            if dbr is not None:
                nr[1] = dbr['first']
                nr[2] = dbr['last']
                nr[3] = dbr['org']
                if self.evtype == 'handicap':  # reqd?
                    if info:
                        nr[COL_INFO] = str(info)
            self.riders.append(nr)
            if self.winopen:
                if self.evtype in ['handicap', 'keirin'] and not self.onestart:
                    self.reorderflag += 1
                    GLib.timeout_add_seconds(1, self.delayed_reorder)
        else:
            if er is not None:
                # Rider already in the model, set the info if
                # event type is handicap or event is part of omnium
                if self.evtype == 'handicap' or self.inomnium:
                    if not er[COL_INFO] and info:  # don't overwrite if set
                        er[COL_INFO] = str(info)

    def dnfriders(self, biblist=''):
        """Remove listed bibs from the race."""
        for bib in biblist.split():
            r = self.getrider(bib)
            if r is not None:
                r[COL_DNF] = True
                _log.info('Rider %r withdrawn', bib)
            else:
                _log.warn('Did not withdraw rider %r', bib)
        return False

    def delrider(self, bib):
        """Remove the specified rider from the model."""
        i = self.getiter(bib)
        if i is not None:
            self.riders.remove(i)

    def placexfer(self, placestr=None):
        """Transfer places in placestr to model."""
        if placestr is not None:
            self.placestr = placestr
        self.finished = False
        self.clearplaces()
        self.results = []
        placeset = set()
        resname_w = self.meet.scb.linelen - 11

        # TODO: Replace riders.swap with single reorder

        # move dnf riders to bottom of list and count inriders
        cnt = 0
        incnt = 0
        reorddnf = []
        if len(self.riders) > 0:
            for r in self.riders:
                if r[COL_DNF]:
                    reorddnf.append(cnt)
                else:
                    incnt += 1
                    reorddnf.insert(0, cnt)
                cnt += 1
            self.riders.reorder(reorddnf)

        # update eliminated rider ranks
        outriders = []
        for bib in self.eliminated:
            r = self.getrider(bib)
            rank = incnt + self.startplace
            r[COL_PLACE] = str(rank)
            club = ''
            if len(r[COL_CLUB]) == 3:
                club = r[COL_CLUB]
            outriders.insert(0, [
                str(rank) + '.', bib,
                strops.fitname(r[COL_FIRSTNAME], r[COL_LASTNAME], resname_w),
                club
            ])
            i = self.getiter(bib)
            incnt -= 1
            self.riders.swap(self.riders.get_iter(incnt), i)

        # overwrite eliminations from placed riders - but warn on overlap
        place = 1
        count = 0
        clubmode = self.meet.get_clubmode()
        for placegroup in self.placestr.split():
            for bib in placegroup.split('-'):
                if bib not in placeset:
                    if count >= incnt and not clubmode:
                        _log.error('Error: More places than available')
                        break
                    placeset.add(bib)
                    r = self.getrider(bib)
                    if r is None:  # ensure rider exists at this point
                        _log.warn('Adding non-starter: %r', bib)
                        self.addrider(bib)
                        r = self.getrider(bib)
                    rank = place + self.startplace
                    r[COL_PLACE] = str(rank)
                    club = ''
                    if len(r[COL_CLUB]) == 3:
                        club = r[COL_CLUB]
                    self.results.append([
                        str(rank) + '.', bib,
                        strops.fitname(r[COL_FIRSTNAME], r[COL_LASTNAME],
                                       resname_w), club
                    ])
                    i = self.getiter(bib)
                    self.riders.swap(self.riders.get_iter(count), i)
                    count += 1
                else:
                    _log.error('Ignoring duplicate no: %r', bib)
            place = count + 1
        self.results.extend(outriders)
        if count > 0 or len(outriders) > 0:
            self.onestart = True
        if count == incnt:
            self.resulttype = 'RESULT'
            self.finished = True
        elif count < incnt and len(outriders) > 0:
            self.resulttype = 'STANDING'
        else:
            self.resulttype = 'PROVISIONAL RESULT'

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
        if self.evtype in ['sprint', 'keirin']:
            deftimetype = '200m'
            defdistunits = 'metres'
            defdistance = '200'
        if self.winopen and self.evtype == 'elimination':
            i = self.action_model.append(['Eliminate', 'out'])
            self.action_model.append(['Un-Eliminate', 'in'])
            if i is not None:
                self.ctrl_action_combo.set_active_iter(i)
        cr = jsonconfig.config({
            'event': {
                'startlist': '',
                'id': EVENT_ID,
                'showcats': False,
                'ctrl_places': '',
                'eliminated': [],
                'start': None,
                'lstart': None,
                'decisions': [],
                'finish': None,
                'distance': defdistance,
                'distunits': defdistunits,
                'showinfo': True,
                'inomnium': False,
                'startplace': 0,
                'autospec': '',
                'timetype': deftimetype
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
        self.showcats = cr.get_bool('event', 'showcats')

        self.autospec = cr.get('event', 'autospec')
        rlist = cr.get('event', 'startlist').split()
        for r in rlist:
            nr = [r, '', '', '', '', False, '']
            if cr.has_option('riders', r):
                ril = cr.get('riders', r)
                for i in range(0, 3):
                    if len(ril) > i:
                        nr[i + 4] = ril[i]
            # Re-patch name
            dbr = self.meet.rdb.get_rider(r, self.series)
            if dbr is not None:
                nr[1] = dbr['first']
                nr[2] = dbr['last']
                nr[3] = dbr['org']
            self.riders.append(nr)

        # race infos
        self.decisions = cr.get('event', 'decisions')
        self.startplace = strops.confopt_posint(cr.get('event', 'startplace'))
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
        places = strops.reformat_placelist(cr.get('event', 'ctrl_places'))

        if self.winopen:
            self.update_expander_lbl_cb()
            self.info_expand.set_expanded(
                strops.confopt_bool(cr.get('event', 'showinfo')))
            self.ctrl_places.set_text(places)

        self.placexfer(places)
        if places:
            self.doscbplaces = False  # only show places on board if not set
            self.setfinished()
        else:
            if self.autospec:
                self.meet.autostart_riders(self,
                                           self.autospec,
                                           infocol=self.seedsrc)
            if self.evtype in ['handicap', 'keirin'] or self.inomnium:
                self.reorder_handicap()

        # After load complete - check config and report.
        eid = cr.get('event', 'id')
        if eid and eid != EVENT_ID:
            _log.info('Event config mismatch: %r != %r', eid, EVENT_ID)

    def sort_riderno(self, x, y):
        """Sort riders by rider no."""
        return cmp(strops.riderno_key(x[1]), strops.riderno_key(y[1]))

    def sort_handicap(self, x, y):
        """Sort function for handicap marks."""
        if x[2] != y[2]:
            if x[2] is None:  # y sorts first
                return 1
            elif y[2] is None:  # x sorts first
                return -1
            else:  # Both should be ints here
                return cmp(x[2], y[2])
        else:  # Defer to rider number
            return cmp(strops.riderno_key(x[1]), strops.riderno_key(y[1]))

    def reorder_handicap(self):
        """Reorder rider model according to the handicap marks."""
        if len(self.riders) > 1:
            auxmap = []
            cnt = 0
            for r in self.riders:
                auxmap.append([cnt, r[COL_BIB], strops.mark2int(r[COL_INFO])])
                cnt += 1
            if self.inomnium or self.evtype == 'handicap':
                auxmap.sort(key=cmp_to_key(self.sort_handicap))
            else:
                auxmap.sort(key=cmp_to_key(self.sort_riderno))
            self.riders.reorder([a[0] for a in auxmap])

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
            self.meet.txt_title(' '.join([
                'Event', self.evno, ':', self.event['pref'], self.event['info']
            ]))
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
                clubstr = ''
                tcs = r[COL_CLUB]
                if tcs and len(tcs) == 3:
                    clubstr = ' (' + tcs + ')'
                namestr = strops.truncpad(strops.fitname(r[COL_FIRSTNAME],
                                                         r[COL_LASTNAME],
                                                         25 - len(clubstr),
                                                         trunc=True) + clubstr,
                                          25,
                                          ellipsis=False)

                placestr = '   '
                if r[COL_PLACE] != '':
                    placestr = strops.truncpad(r[COL_PLACE] + '.', 3)
                elif r[COL_DNF]:
                    placestr = 'dnf'
                bibstr = strops.truncpad(r[COL_BIB], 3, 'r')
                self.meet.txt_postxt(
                    curline, posoft,
                    ' '.join([placestr, bibstr, namestr, xtra]))
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
        return False

    def startlist_report(self, program=False):
        """Return a startlist report."""
        ret = []
        sec = None
        etype = self.event['type']
        twocol = True
        rankcol = None
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        if not self.inomnium and not program and etype in ['axe', 'run']:
            sec = report.section(secid)  # one column overrides
        else:
            sec = report.twocol_startlist(secid)

        sec.nobreak = True
        headvec = []
        if etype != 'break':
            headvec.extend(['Event', self.evno, ':'])
        headvec.append(self.event['pref'])
        headvec.append(self.event['info'])
        if not program:
            headvec.append('- Start List')
        else:
            rankcol = ' '
        sec.heading = ' '.join(headvec)
        lapstring = strops.lapstring(self.event['laps'])
        substr = ' '.join([lapstring, self.event['dist'],
                           self.event['prog']]).strip()
        if substr:
            sec.subheading = substr

        self.reorder_handicap()
        sec.lines = []
        cnt = 0
        col2 = []
        if self.inomnium and len(self.riders) > 0:
            pass
            #sec.lines.append([' ', ' ', 'The Fence', None, None, None])
            #col2.append([' ', ' ', 'Sprinters Lane', None, None, None])
        for r in self.riders:
            cnt += 1
            rno = r[COL_BIB]
            rh = self.meet.rdb.get_rider(rno, self.series)
            inf = r[COL_INFO]
            if self.evtype in ['keirin', 'sprint']:  # encirc draw no
                inf = strops.drawno_encirc(inf)
            if self.inomnium:
                # inf holds seed, ignore for now
                inf = None
            if self.showcats and rh is not None:
                inf = rh.primary_cat()
            rname = ''
            if rh is not None:
                rname = rh.resname()
            if self.inomnium:
                if cnt % 2 == 1:
                    sec.lines.append([rankcol, rno, rname, inf, None, None])
                else:
                    col2.append([rankcol, rno, rname, inf, None, None])
            else:
                sec.lines.append([rankcol, rno, rname, inf, None, None])
        for i in col2:
            sec.lines.append(i)
        if self.event['plac']:
            while cnt < self.event['plac']:
                sec.lines.append([rankcol, None, None, None, None, None])
                cnt += 1

        # Prizemoney line
        pvec = []
        if self.event['prizemoney']:
            count = 0
            for place in self.event['prizemoney'].split():
                count += 1
                if place.isdigit():
                    placeval = int(place)
                    rank = strops.rank2ord(str(count))
                    pvec.append('%s $%d: ____' % (rank, placeval))
                elif place == '-':
                    rank = strops.rank2ord(str(count))
                    pvec.append('%s: ____' % (rank, ))
                else:
                    pvec.append('%s: ____' % (place, ))
        if pvec:
            sec.prizes = '\u2003'.join(pvec)

        # Footer line
        fvec = []
        ptype = 'Riders'
        if etype == 'run':
            ptype = 'Runners'
        elif self.evtype == 'axe':
            ptype = 'Axemen'
        if cnt > 2:
            fvec.append('Total %s: %d' % (ptype, cnt))
        if self.event['reco']:
            fvec.append(self.event['reco'])
        if self.event['sponsor']:
            fvec.append('Sponsor: ' + self.event['sponsor'])

        if fvec:
            sec.footer = '\u2003'.join(fvec)

        ret.append(sec)
        return ret

    def get_startlist(self):
        """Return a list of bibs in the rider model."""
        ret = []
        for r in self.riders:
            ret.append(r[COL_BIB])
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
        cw.set('event', 'ctrl_places', self.ctrl_places.get_text())
        cw.set('event', 'eliminated', self.eliminated)
        cw.set('event', 'startlist', self.get_startlist())
        cw.set('event', 'showinfo', self.info_expand.get_expanded())
        cw.set('event', 'distance', self.distance)
        cw.set('event', 'distunits', self.units)
        cw.set('event', 'timetype', self.timetype)
        cw.set('event', 'autospec', self.autospec)
        cw.set('event', 'inomnium', self.inomnium)
        cw.set('event', 'showcats', self.showcats)
        cw.set('event', 'decisions', self.decisions)
        cw.set('event', 'startplace', self.startplace)

        cw.add_section('riders')
        for r in self.riders:
            cw.set('riders', r[COL_BIB],
                   [r[COL_INFO], r[COL_DNF], r[COL_PLACE]])
        cw.set('event', 'id', EVENT_ID)
        _log.debug('Saving event config %r', self.configfile)
        with metarace.savefile(self.configfile) as f:
            cw.write(f)

    def shutdown(self, win=None, msg='Exit'):
        """Terminate event object."""
        rstr = ''
        if self.readonly:
            rstr = 'readonly '
        _log.debug('Shutdown %sevent %s: %s', rstr, self.evno, msg)
        if not self.readonly:
            self.saveconfig()
        self.winopen = False

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
        as_e.set_text(self.autospec)
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

            # update auto startlist spec
            nspec = as_e.get_text()
            if nspec != self.autospec:
                self.autospec = nspec
                if not self.ctrl_places.get_text():
                    if self.autospec:
                        self.meet.autostart_riders(self, self.autospec,
                                                   self.seedsrc)
                    if self.evtype == 'handicap':
                        self.reorder_handicap()

            # xfer starters if not empty
            slist = strops.riderlist_split(
                b.get_object('race_starters_entry').get_text(), self.meet.rdb,
                self.series)
            for s in slist:
                self.addrider(s)
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
                    self.doscbplaces = True  # override if already clear
                    self.do_places()
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
            FMT = [(3, 'l'), (3, 'r'), ' ', (self.meet.scb.linelen - 11, 'l'),
                   (4, 'r')]
            self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                               head=self.meet.racenamecat(
                                                   self.event),
                                               subhead=self.resulttype,
                                               coldesc=FMT,
                                               rows=self.results,
                                               timepfx=tp,
                                               timestr=ts)
            self.meet.scbwin.reset()
            self.doscbplaces = False
        self.setfinished()

    def do_startlist(self):
        """Show start list on scoreboard."""

        self.reorder_handicap()
        self.meet.scbwin = None
        self.timerwin = False
        startlist = []
        ##self.meet.announce.gfx_overlay(1)
        ##self.meet.announce.gfx_set_title(u'Startlist: '
        ##+ self.event[u'pref'] + u' '
        ##+ self.event[u'info'])
        name_w = self.meet.scb.linelen - 8
        for r in self.riders:
            if not r[COL_DNF]:
                nfo = r[COL_INFO]
                club = ''
                if len(r[COL_CLUB]) == 3:
                    club = r[COL_CLUB]
                if self.evtype in ['sprint']:  # add asterisk
                    nfo = nfo + club
                if not nfo:
                    nfo = club
                startlist.append([
                    r[COL_BIB],
                    strops.fitname(r[COL_FIRSTNAME], r[COL_LASTNAME], name_w),
                    nfo
                ])
        FMT = [(3, 'r'), ' ', (name_w, 'l'), (4, 'r')]
        self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                           head=self.meet.racenamecat(
                                               self.event),
                                           subhead='STARTLIST',
                                           coldesc=FMT,
                                           rows=startlist)
        self.meet.scbwin.reset()

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
            lr = self.getrider(no)
            if lr is None:
                if not self.meet.get_clubmode():
                    _log.error('Non-starter in places: %r', no)
                    ret = False
                # otherwise club mode allows non-starter in places
            else:
                # rider still in the race?
                if lr[COL_DNF]:
                    _log.error('DNF rider in places: %r', no)
                    ret = False
        return ret

    def race_ctrl_places_activate_cb(self, entry, data=None):
        """Respond to activate on place entry."""
        places = strops.reformat_placelist(entry.get_text())
        if self.checkplaces(places):
            self.placestr = places
            _log.debug('Event %r places updated: %r', self.evno, self.placestr)
            entry.set_text(self.placestr)
            self.do_places()
            GLib.idle_add(self.delayed_announce)
            self.meet.delayed_export()
        else:
            _log.error('Places not updated')

    def race_ctrl_action_activate_cb(self, entry, data=None):
        """Perform current action on bibs listed."""
        rlist = entry.get_text()
        acode = self.action_model.get_value(
            self.ctrl_action_combo.get_active_iter(), 1)
        if acode == 'dnf':
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
        elif acode == 'out' and self.evtype == 'elimination':
            bib = rlist.strip()
            if self.eliminate(bib):
                entry.set_text('')
            # Short-circuit method to avoid re-announce
            return False
        elif acode == 'in' and self.evtype == 'elimination':
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
        r = self.getrider(bib)
        if r is not None:
            if not r[COL_DNF]:
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

        return ret

    def eliminate(self, bib):
        """Register rider as eliminated."""
        ret = False
        r = self.getrider(bib)
        if r is not None:
            if not r[COL_DNF]:
                if bib not in self.eliminated:
                    self.eliminated.append(bib)
                    self.placexfer()
                    _log.error('Rider %r eliminated', bib)
                    ret = True
                    fname = r[COL_FIRSTNAME]
                    lname = r[COL_LASTNAME]
                    club = ''
                    if len(r[COL_CLUB]) == 3:
                        club = r[COL_CLUB]
                    rno = r[COL_BIB]
                    rstr = (rno + ' ' + strops.fitname(
                        fname, lname, self.meet.scb.linelen - 3 - len(rno)))
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
                    # announce it:
                    nrstr = strops.truncpad(
                        strops.resname_bib(r[COL_BIB], r[COL_FIRSTNAME],
                                           r[COL_LASTNAME], club), 60)
                    self.meet.txt_postxt(21, 0, 'Out: ' + nrstr)
                    GLib.timeout_add_seconds(10, self.delayed_result)
                else:
                    _log.error('Rider %r already eliminated', bib)
            else:
                _log.error('Cannot eliminate dnf rider: %r', bib)
        else:
            _log.error('Cannot eliminate non-starter: %r', bib)

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
        self.meet.gemini.clear()
        GLib.idle_add(self.delayed_announce)

    def editent_cb(self, entry, col):
        """Shared event entry update callback."""
        if col == 'pref':
            self.event['pref'] = entry.get_text()
        elif col == 'info':
            self.event['info'] = entry.get_text()
        self.update_expander_lbl_cb()

    def editcol_cb(self, cell, path, new_text, col):
        """Startlist cell update callback."""
        new_text = new_text.strip()
        if col != COL_BIB:
            self.riders[path][col] = new_text.strip()
        else:
            if new_text.isalnum():
                if self.getrider(new_text) is None:
                    self.riders[path][COL_BIB] = new_text
                    dbr = self.meet.rdb.get_rider(new_text, self.series)
                    if dbr is not None:
                        self.riders[path][1] = dbr['first']
                        self.riders[path][2] = dbr['last']
                        self.riders[path][3] = dbr['org']

    def editcol_db(self, cell, path, new_text, col):
        """Cell update with writeback to meet."""
        new_text = new_text.strip()
        self.riders[path][col] = new_text
        dbr = self.meet.rdb.get_rider(self.riders[path][COL_BIB], self.series)
        if dbr is None:
            self.meet.rdb.add_empty(self.riders[path][COL_BIB], self.series)
            dbr = self.meet.rdb.get_rider(self.riders[path][COL_BIB],
                                          self.series)
        if dbr is not None:
            if col == COL_FIRSTNAME:
                dbr['first'] = new_text
            elif col == COL_LASTNAME:
                dbr['last'] = new_text
            elif col == COL_CLUB:
                dbr['org'] = new_text
            else:
                _log.debug('Ignore update to unknown column')

    def gotorow(self, i=None):
        """Select row for specified iterator."""
        if i is None:
            i = self.riders.get_iter_first()
        if i is not None:
            self.view.scroll_to_cell(self.riders.get_path(i))
            self.view.set_cursor_on_cell(self.riders.get_path(i))

    def dnf_cb(self, cell, path, col):
        """Toggle rider dnf flag."""
        self.riders[path][col] = not self.riders[path][col]

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
            bib = r[COL_BIB]
            rank = None
            info = ''
            if self.evtype in ('handicap', 'sprint'):
                # include handicap and previous win info
                info = r[COL_INFO].strip()
            if self.onestart:
                if not r[COL_DNF]:
                    if r[COL_PLACE]:
                        rank = int(r[COL_PLACE])
                else:
                    inft = r[COL_INFO]
                    if inft in ('dns', 'dsq'):
                        rank = inft
                    else:
                        rank = 'dnf'
            time = None
            if self.finish is not None and ft is None:
                time = (self.finish - self.start).rawtime(2)
                ft = True
            yield (bib, rank, time, info)

    def result_report(self, recurse=False):
        """Return a list of report sections containing the race result."""
        self.placexfer()
        ret = []
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)
        sec.nobreak = True
        sec.heading = 'Event ' + self.evno + ': ' + ' '.join(
            [self.event['pref'], self.event['info']]).strip()
        sec.lines = []
        lapstring = strops.lapstring(self.event['laps'])
        substr = ' '.join([lapstring, self.event['dist'],
                           self.event['prog']]).strip()
        first = True
        fs = ''
        if self.finish is not None and self.start is not None:
            fs = (self.finish - self.start).rawtime(2)
        rcount = 0
        pcount = 0
        for r in self.riders:
            plstr = ''
            rcount += 1
            rno = r[COL_BIB]
            rh = self.meet.rdb.get_rider(rno, self.series)
            rname = ''
            if rh is not None:
                rname = rh.resname()
            inf = r[COL_INFO].strip()
            if self.evtype in ['keirin', 'sprint']:  # encirc draw no
                inf = strops.drawno_encirc(inf)
            if r[COL_DNF]:
                pcount += 1
                if r[COL_INFO] in ['dns', 'dsq']:
                    plstr = r[COL_INFO]
                    inf = None
                else:
                    plstr = 'dnf'
            elif self.onestart and r[COL_PLACE] != '':
                plstr = r[COL_PLACE] + '.'
                pcount += 1
            # but suppress inf if within an omnium
            if self.inomnium:
                inf = None
            if self.evtype != 'handicap' and rh is not None and rh['ucicode']:
                inf = rh['ucicode']  # overwrite by force
            if self.showcats and rh is not None:
                inf = rh.primary_cat()
            if plstr:  # don't emit a row for unplaced riders
                if not first:
                    sec.lines.append([plstr, rno, rname, inf, None, None])
                else:
                    sec.lines.append([plstr, rno, rname, inf, fs, None])
                    first = False
        if self.onestart:
            substr = substr.strip()
            shvec = []
            if substr:
                shvec.append(substr)
            shvec.append(self.standingstr())
            sec.subheading = ' - '.join(shvec)
        else:
            if substr:
                sec.subheading = substr

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
                if r[COL_DNF]:
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

    def destroy(self):
        """Signal race shutdown."""
        self.frame.destroy()

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
        self.placestr = ''
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
        self.startplace = 0  # offset to first place in this race (hack)
        self.autospec = ''  # automatic startlist
        self.inomnium = False
        self.showcats = False
        self.seedsrc = None
        self.doscbplaces = True  # auto show result on scb
        self.reorderflag = 0
        self.startchan = 0
        self.finchan = 1
        self.finished = False

        self.riders = Gtk.ListStore(
            str,  # 0 bib
            str,  # 1 first name
            str,  # 2 last name
            str,  # 3 club
            str,  # 4 xtra info
            bool,  # 5 DNF/DNS
            str)  # 6 placing

        # start timer and show window
        if ui:
            b = uiutil.builder('race.ui')
            self.frame = b.get_object('race_vbox')
            self.frame.connect('destroy', self.shutdown)

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
            uiutil.mkviewcoltxt(t, 'No.', COL_BIB, calign=1.0)
            uiutil.mkviewcoltxt(t,
                                'First Name',
                                COL_FIRSTNAME,
                                self.editcol_db,
                                expand=True)
            uiutil.mkviewcoltxt(t,
                                'Last Name',
                                COL_LASTNAME,
                                self.editcol_db,
                                expand=True)
            uiutil.mkviewcoltxt(t, 'Club', COL_CLUB, self.editcol_db)
            uiutil.mkviewcoltxt(t, 'Info', COL_INFO, self.editcol_cb)
            uiutil.mkviewcolbool(t, 'DNF', COL_DNF, self.dnf_cb)
            uiutil.mkviewcoltxt(t,
                                'Place',
                                COL_PLACE,
                                self.editcol_cb,
                                halign=0.5,
                                calign=0.5)
            t.show()
            b.get_object('race_result_win').add(t)
            b.connect_signals(self)
