# SPDX-License-Identifier: MIT
"""Flying 200m and lap time trial module for trackmeet."""

# Refer: UCI Regulations Part 3 "Track Races" 3.2.022 - 3.2.028
# 	 and 3.2.253 - 3.2.258

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

_log = logging.getLogger('f200')
_log.setLevel(logging.DEBUG)

# config version string
EVENT_ID = 'f200-2.1'

# race model columns
COL_NO = 0
COL_NAME = 1
COL_COMMENT = 4
COL_SEED = 5
COL_PLACE = 6
COL_START = 7
COL_FINISH = 8
COL_100 = 9

# scb function key mappings (also trig announce)
key_reannounce = 'F4'  # (+CTRL) calls into delayed announce
key_startlist = 'F3'  # startlist
key_results = 'F4'  # recalc/show result window
key_timerwin = 'F6'  # re-show timing window

# timing function key mappings
key_armstart = 'F5'  # arm for start impulse
key_armsplit = 'F7'  # de/arm intermed (manual override)
key_armfinish = 'F9'  # de/arm finish (manual override)

# extended function key mappings
key_reset = 'F5'  # + ctrl for clear/abort
key_falsestart = 'F6'  # + ctrl for false start
key_abort = 'F7'  # + ctrl abort A


# temporary
def cmp(x, y):
    if x < y:
        return -1
    elif x > y:
        return 1
    else:
        return 0


class f200:
    """Flying 200 time trial."""

    def show_lapscore(self, laps, prev):
        """Reject lapscore updates"""
        return False

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

    def standingstr(self):
        return self._standingstr

    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == Gdk.EventType.KEY_PRESS:
            key = Gdk.keyval_name(event.keyval) or 'None'
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                if key == key_reset:  # override ctrl+f5
                    self.toidle()
                    return True
                elif key == key_reannounce:
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_falsestart:
                    self.falsestart()
                    return True
                elif key == key_abort:
                    self.abortrider(self.fs)
                    return True
            elif key[0] == 'F':
                if key == key_armstart:
                    self.armstart()
                    return True
                elif key == key_armsplit:
                    self.armsplit(self.fs)
                    return True
                elif key == key_armfinish:
                    self.armfinish(self.fs)
                    return True
                elif key == key_startlist:
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_timerwin:
                    self.showtimerwin()
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_results:
                    self.do_places()
                    GLib.idle_add(self.delayed_announce)
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
        ret['competitionType'] = 'single'  # for all flying 200/lap
        ret['status'] = self._status
        if self._startlines is not None:
            ret['competitors'] = self._startlines
        if self._reslines is not None:
            ret['lines'] = self._reslines
        if self._detail is not None:
            ret['detail'] = self._detail
        if self._infoLine is not None:
            ret['info'] = self._infoLine

        # competitor details
        if self._competitorA is not None:
            ret['competitorA'] = self._competitorA
        if self._timeA is not None:
            ret['timeA'] = self._timeA
        if self._labelA is not None:
            ret['labelA'] = self._labelA
        if self._downA is not None:
            ret['downA'] = self._downA
        if self._rankA is not None:
            ret['rankA'] = self._rankA

        # rolling time
        if self._endA is not None:
            ret['startTime'] = self._startA
            ret['endTime'] = self._endA
        elif self.lstart is not None:
            ret['startTime'] = self.lstart

        if len(self.decisions) > 0:
            ret['decisions'] = self.meet.decision_list(self.decisions)
        return ret

    def do_places(self):
        """Show race result on scoreboard."""
        self.meet.scbwin = None
        self.timerwin = False
        fmtplaces = []
        name_w = self.meet.scb.linelen - 12
        fmt = ((3, 'l'), (3, 'r'), ' ', (name_w, 'l'), (5, 'r'))
        pcount = 0
        rcount = 0
        for r in self.riders:
            rcount += 1
            if r[COL_PLACE] is not None and r[COL_PLACE] != '':
                pcount += 1
                plstr = r[COL_PLACE]
                if plstr.isdigit():
                    plstr += '.'
                name, club, cls = self._getname(r[COL_NO], width=name_w)
                if not cls and len(club) == 3:
                    cls = club
                bib = r[COL_NO]
                fmtplaces.append((plstr, bib, name, cls))

        evtstatus = 'Standings'
        if rcount > 0 and pcount == rcount:
            evtstatus = 'Result'

        self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                           head=self.meet.racenamecat(
                                               self.event),
                                           subhead=evtstatus.upper(),
                                           coldesc=fmt,
                                           rows=fmtplaces)
        self.meet.scbwin.reset()

    def todstr(self, col, cr, model, iter, data=None):
        """Format tod into text for listview."""
        ft = model.get_value(iter, COL_FINISH)
        if ft is not None:
            sp = model.get_value(iter, COL_100)
            st = model.get_value(iter, COL_START)
            if st is None:
                st = tod.tod(0)
            mstr = (ft - st).rawtime(3)
            sstr = ''
            if sp is not None:
                sstr = '/' + (ft - sp).rawtime(3)
            cr.set_property('text', mstr + sstr)
        else:
            cr.set_property('text', '')

    def loadconfig(self):
        """Load race config from disk."""
        self.riders.clear()
        self.results.clear()
        self.splits.clear()

        defautoarm = True
        defdistance = 200
        defunits = 'metres'
        defchans = 4
        defchani = 5
        defchanf = 1
        if self.evtype == 'flying lap':
            # override defaults for flying lap type
            defdistance = 1
            defunits = 'laps'
            defchans = 1
            defchani = 4
            defchanf = 1

        self.seedsrc = 1  # for autospec loads, fetch seed from the rank col

        cr = jsonconfig.config({
            'event': {
                'startlist': '',
                'id': EVENT_ID,
                'start': None,
                'lstart': None,
                'fsbib': None,
                'fsstat': 'idle',
                'showinfo': False,
                'decisions': [],
                'chan_S': defchans,
                'chan_I': defchani,
                'chan_F': defchanf,
                'inomnium': False,
                'distance': defdistance,
                'distunits': defunits,
                'autoarm': defautoarm,
                'weather': None,
            }
        })
        cr.add_section('event')
        cr.add_section('riders')
        cr.add_section('traces')
        if not cr.load(self.configfile):
            _log.info('%r not read, loading defaults', self.configfile)

        self.chan_S = strops.confopt_chan(cr.get('event', 'chan_S'), defchans)
        self.chan_I = strops.confopt_chan(cr.get('event', 'chan_I'), defchans)
        self.chan_F = strops.confopt_chan(cr.get('event', 'chan_F'), defchans)
        self._weather = cr.get('event', 'weather')
        self.decisions = cr.get('event', 'decisions')
        self.distance = strops.confopt_dist(cr.get('event', 'distance'))
        self.units = strops.confopt_distunits(cr.get('event', 'distunits'))
        self.autoarm = strops.confopt_bool(cr.get('event', 'autoarm'))

        self.inomnium = strops.confopt_bool(cr.get('event', 'inomnium'))
        if self.inomnium:
            self.seedsrc = 3  # read seeding from points standinds

        # re-load starters/results and traces
        self.onestart = False
        rlist = cr.get('event', 'startlist').upper().split()
        for r in rlist:
            nr = [r, '', '', '', '', '', '', None, None, None]
            co = ''
            st = None
            ft = None
            sp = None
            if cr.has_option('riders', r):
                ril = cr.get('riders', r)
                if len(ril) >= 1:  # save comment for stimes
                    co = ril[0]
                if len(ril) >= 2:  # write heat into rec
                    nr[COL_SEED] = ril[1]
                if len(ril) >= 4:  # Start ToD and others
                    st = tod.mktod(ril[3])
                    if st is not None:  # assigned in settimes
                        self.onestart = True
                if len(ril) >= 5:  # Finish ToD
                    ft = tod.mktod(ril[4])
                if len(ril) >= 6:  # 100m ToD
                    sp = tod.mktod(ril[5])
            dbr = self.meet.rdb.get_rider(r, self.series)
            if dbr is not None:
                nr[COL_NAME] = dbr.listname()
            nri = self.riders.append(nr)
            if not self.readonly:
                if cr.has_option('traces', r):
                    self.traces[r] = cr.get('traces', r)
            self.settimes(nri, st, ft, sp, doplaces=False, comment=co)
        self.placexfer()

        if not self.onestart and self.event['auto']:
            self.riders.clear()
            self.meet.autostart_riders(self,
                                       self.event['auto'],
                                       infocol=self.seedsrc)

        if self.winopen:
            self.update_expander_lbl_cb()
            self.info_expand.set_expanded(
                strops.confopt_bool(cr.get('event', 'showinfo')))

            # re-join an existing timer state
            curstart = tod.mktod(cr.get('event', 'start'))
            lstart = tod.mktod(cr.get('event', 'lstart'))
            if lstart is None:
                lstart = curstart  # can still be None if start not set
            dorejoin = False
            fsstat = cr.get('event', 'fsstat')
            if fsstat not in ('idle', 'finish'):
                self.fs.setrider(cr.get('event', 'fsbib'))  # load rider
                if fsstat in ('running', 'armfin',
                              'armint') and curstart is not None:
                    self.fs.start(curstart)  # overrides to 'running'
                    dorejoin = True
            if dorejoin:
                self.torunning(curstart, lstart)
            elif self.timerstat == 'idle':
                GLib.idle_add(self.fs.grab_focus)
        else:
            # cache showinfo, start, lstart, fsstat and fsbib
            for key in (
                    'lstart',
                    'start',
                    'fsstat',
                    'fsbib',
                    'showinfo',
            ):
                self._winState[key] = cr.get('event', key)

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
        cw.add_section('event')

        # save basic race properties
        cw.set('event', 'distance', self.distance)
        cw.set('event', 'weather', self._weather)
        cw.set('event', 'distunits', self.units)
        cw.set('event', 'chan_S', self.chan_S)
        cw.set('event', 'chan_I', self.chan_I)
        cw.set('event', 'chan_F', self.chan_F)
        cw.set('event', 'autoarm', self.autoarm)
        cw.set('event', 'startlist', self.get_startlist())
        cw.set('event', 'inomnium', self.inomnium)

        _log.debug('winopen: %r', self.winopen)
        if self.winopen:
            cw.set('event', 'showinfo', self.info_expand.get_expanded())
            cw.set('event', 'fsstat', self.fs.getstatus())
            _log.debug('fsbib: %r', self.fs.getrider())
            cw.set('event', 'fsbib', self.fs.getrider())
            cw.set('event', 'start', self.curstart)
            cw.set('event', 'lstart', self.lstart)
        else:
            for key in (
                    'lstart',
                    'start',
                    'fsstat',
                    'fsbib',
                    'showinfo',
            ):
                cw.set('event', key, self._winState[key])
        cw.set('event', 'decisions', self.decisions)

        cw.add_section('riders')
        cw.add_section('traces')

        # save out all starters
        for r in self.riders:
            rno = r[COL_NO]
            # place is saved for info only
            slice = [r[COL_COMMENT], r[COL_SEED], r[COL_PLACE]]
            tl = [r[COL_START], r[COL_FINISH], r[COL_100]]
            for t in tl:
                if t is not None:
                    slice.append(t.rawtime())
                else:
                    slice.append(None)
            cw.set('riders', rno, slice)

            # save timing traces
            if rno in self.traces:
                cw.set('traces', rno, self.traces[rno])

        cw.set('event', 'id', EVENT_ID)
        _log.debug('Saving event config %r', self.configfile)
        with metarace.savefile(self.configfile) as f:
            cw.write(f)

    def sort_startlist(self, x, y):
        """Comparison function for seeding."""
        if x[1] == y[1]:  # same seed? revert to bib ascending
            return cmp(x[2], y[2])
        else:
            return cmp(x[1], y[1])

    def sort_heats(self, x, y):
        """Comparison function for heats."""
        (xh, xl) = strops.heatsplit(x[0])
        (yh, yl) = strops.heatsplit(y[0])
        if xh == yh:
            return cmp(xl, yl)
        else:
            return cmp(xh, yh)

    def reorder_startlist(self):
        """Re-order model according to the seeding field."""
        if len(self.riders) > 1:
            auxmap = []
            cnt = 0
            for r in self.riders:
                auxmap.append([
                    cnt,
                    strops.riderno_key(r[COL_SEED]),
                    strops.riderno_key(r[COL_NO])
                ])
                cnt += 1
            auxmap.sort(key=cmp_to_key(self.sort_startlist))
            self.riders.reorder([a[0] for a in auxmap])

    def get_heats(self, placeholders=0):
        """Return a list of heats in the event."""
        ret = []

        # arrange riders by seeding
        self.reorder_startlist()

        # then build aux map of heats
        self._startlines = []
        hlist = []
        count = len(self.riders)
        if count < placeholders:
            count = placeholders
        if placeholders == 0:
            for r in self.riders:
                rno = r[COL_NO]
                rh = self.meet.rdb.get_rider(rno, self.series)
                info = None
                rname = ''
                rnat = None
                if rh is not None:
                    rname = rh.resname()
                    rnat = rh['nation']
                    info = rh['class']
                    # TODO: PARA Pilots
                    #if rh.in_cat('tandem') and rh['note']:
                    #ph = self.meet.rdb.get_rider(rh['note'], self.series)
                    #if ph is not None:
                    #info = [[
                    #' ',
                    #ph.resname() + ' - Pilot', ph['uciid']
                    #]]
                hlist.append([str(count) + '.1', rno, rname, info, rnat])
                # all f200 heats are one up
                count -= 1
        else:
            for r in range(0, placeholders):
                rno = ''
                rname = ''
                hlist.append([str(count) + '.1', rno, rname, None, None])
                count -= 1

        # sort the heatlist
        hlist.sort(key=cmp_to_key(self.sort_heats))

        lh = None
        lcnt = 0
        rec = []
        for r in hlist:
            (h, l) = strops.heatsplit(r[0])
            if lh is not None and (h != lh or lcnt > 1):
                lcnt = 0
                ret.append(rec)
                rec = []
            heat = str(h)
            rec.extend([heat, r[1], r[2], r[3]])
            lcnt += 1
            lh = h
            if r[1]:
                self._startlines.append({
                    'competitor': r[1],
                    'nation': r[4],
                    'name': r[2],
                    'info': r[3],
                })
        if len(rec) > 0:
            ret.append(rec)
        return ret

    def startlist_report(self, program=False):
        """Return a startlist report."""
        ret = []
        cnt = 0
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.dual_ittt_startlist(secid)
        sec.nobreak = True
        sec.set_single()  # 200s are one-up
        headvec = self.event.get_info(showevno=True).split()
        if not program:
            headvec.append('- Start List')
        sec.heading = ' '.join(headvec)
        lapstring = strops.lapstring(self.event['laps'])
        substr = ' '.join(
            (lapstring, self.event['distance'], self.event['rules'])).strip()
        if substr:
            sec.subheading = substr
        sec.lines = self.get_heats()

        # Prizemoney line
        sec.prizes = self.meet.prizeline(self.event)

        # Footer line (suppressed competitor count)
        sec.footer = self.meet.footerline(self.event)

        ret.append(sec)
        return ret

    def get_startlist(self):
        """Return a list of bibs in the rider model."""
        ret = []
        for r in self.riders:
            ret.append(r[COL_NO])
        return ' '.join(ret)

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        if self.winopen:
            # clear page
            self.meet.txt_clear()
            self.meet.txt_title(self.event.get_info(showevno=True))
            self.meet.txt_line(1)
            self.meet.txt_line(7)

            # fill in front straight (only one?)
            fbib = self.fs.getrider()
            if fbib:
                r = self._getrider(fbib)
                if r is not None:
                    namestr = strops.truncpad(r[COL_NAME], 24)
                    placestr = '   '  # 3 ch
                    if r[COL_PLACE]:
                        placestr = strops.truncpad(r[COL_PLACE] + '.', 3)
                    bibstr = strops.truncpad(r[COL_NO], 3, 'r')
                    tmstr = ''
                    et = None
                    if r[COL_START] is not None and r[COL_FINISH] is not None:
                        et = (r[COL_FINISH] - r[COL_START]).truncate(3)
                        tmstr = '200m: ' + et.rawtime(3).rjust(12)
                    cmtstr = ''
                    if et is not None:
                        cmtstr = strops.truncpad(
                            'Average: ' + et.speedstr(200), 38, 'r')
                    elif r[COL_COMMENT]:
                        cmtstr = strops.truncpad(
                            '[' + r[COL_COMMENT].strip() + ']', 38, 'r')
                    self.meet.txt_postxt(3, 0, '        Current Rider')
                    self.meet.txt_postxt(4, 0, ' '.join(
                        (placestr, bibstr, namestr)))
                    self.meet.txt_postxt(5, 0, strops.truncpad(tmstr, 38, 'r'))
                    self.meet.txt_postxt(6, 0, cmtstr)

            # fill in leaderboard/startlist
            count = 0
            curline = 9
            posoft = 0
            for r in self.riders:
                count += 1
                if count == 19:
                    curline = 9
                    posoft += 42
                namestr = strops.truncpad(r[COL_NAME], 22)
                placestr = '   '  # 3 ch
                if r[COL_PLACE]:
                    placestr = strops.truncpad(r[COL_PLACE] + '.', 3)
                bibstr = strops.truncpad(r[COL_NO], 3, 'r')
                tmstr = '       '  # 7 ch
                if r[COL_START] is not None and r[COL_FINISH] is not None:
                    tmstr = strops.truncpad(
                        (r[COL_FINISH] - r[COL_START]).rawtime(3), 7, 'r')
                self.meet.txt_postxt(
                    curline, posoft, ' '.join(
                        (placestr, bibstr, namestr, tmstr)))
                curline += 1
            self.resend_current()

    def do_properties(self):
        """Run event properties dialog."""
        b = uiutil.builder('ittt_properties.ui')
        dlg = b.get_object('properties')
        dlg.set_transient_for(self.meet.window)

        # customise dialog for flying 200/flying lap
        b.get_object('race_score_type').hide()
        b.get_object('race_timing_label').hide()
        intlbltxt = '100m Channel:'
        inthint = 'Select timing channel for 100m split.'
        if self.evtype == 'flying lap':
            intlbltxt = '200m Channel:'
            inthint = 'Select timing channel for 200m start.'
        intlbl = b.get_object('race_achan_label')
        intlbl.set_text(intlbltxt)
        intcombo = b.get_object('race_achan_combo')
        intcombo.set_property('tooltip_text', inthint)
        intcombo.set_active(self.chan_I)
        finlbl = b.get_object('race_bchan_label')
        finlbl.set_text('Finish Channel:')
        fincombo = b.get_object('race_bchan_combo')
        fincombo.set_property('tooltip_text',
                              'Select timing channel for finish.')
        fincombo.set_active(self.chan_F)
        stcombo = b.get_object('race_stchan_combo')
        stcombo.set_active(self.chan_S)
        aa = b.get_object('race_autoarm_toggle')
        aa.set_active(self.autoarm)

        di = b.get_object('race_dist_entry')
        if self.distance is not None:
            di.set_text(str(self.distance))
        else:
            di.set_text('')
        du = b.get_object('race_dist_type')
        if self.units == 'laps':
            du.set_active(1)
        else:
            du.set_active(0)
        se = b.get_object('race_series_entry')
        se.set_text(self.series)
        as_e = b.get_object('auto_starters_entry')
        as_e.set_text(self.event['starters'])

        response = dlg.run()
        if response == 1:  # id 1 set in glade for "Apply"
            dval = di.get_text()
            if dval.isdigit():
                self.distance = int(dval)
            else:
                self.distance = None
            if du.get_active() == 0:
                self.units = 'metres'
            else:
                self.units = 'laps'
            self.autoarm = aa.get_active()
            self.chan_S = stcombo.get_active()
            self.chan_I = intcombo.get_active()
            self.chan_F = fincombo.get_active()

            # update series
            ns = se.get_text()
            if ns != self.series:
                self.series = ns
                self.event['seri'] = ns

            # update auto startlist spec
            nspec = as_e.get_text()
            if nspec != self.event['starters']:
                self.event.set_value('starters', nspec)
                if not self.onestart:
                    self.riders.clear()
                    if nspec:
                        self.meet.autostart_riders(self,
                                                   nspec,
                                                   infocol=self.seedsrc)

            # xfer starters if not empty
            slist = strops.riderlist_split(
                b.get_object('race_starters_entry').get_text(), self.meet.rdb,
                self.series)

            # if no starters yet - automatically seed by order entered
            if len(self.riders) == 0:
                cnt = 1
                for s in slist:
                    self.addrider(s, cnt)
                    cnt += 1
            else:
                for s in slist:
                    self.addrider(s)
            GLib.idle_add(self.delayed_announce)
        else:
            _log.debug('Edit event properties cancelled')

        # if prefix is empty, grab input focus
        if not self.prefix_ent.get_text():
            self.prefix_ent.grab_focus()
        dlg.destroy()

    def result_gen(self):
        """Generator function to export rankings."""
        for r in self.riders:
            bib = r[COL_NO]
            rank = None
            time = None
            info = None
            cmts = r[COL_COMMENT]
            if cmts in ('rel', ):
                info = cmts
            if self.onestart:
                pls = r[COL_PLACE]
                if pls:
                    if pls.isdigit():
                        rank = int(pls)
                    else:
                        rank = pls
                if r[COL_FINISH] is not None:
                    time = (r[COL_FINISH] - r[COL_START]).truncate(3)

            yield (bib, rank, time, info)

    def data_bridge(self):
        """Export data bridge fragments, startlists and results"""
        fragment = self.event.get_fragment()
        if fragment:
            data = self.data_pack()
            self.meet.db.updateFragment(self.event, fragment, data)

    def result_report(self, recurse=False):
        """Return a list of report sections containing the race result."""
        slist = self.startlist_report()  # keep for unfinished
        finriders = set()
        self.placexfer()
        ret = []
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)
        sec.nobreak = True
        sec.heading = self.event.get_info(showevno=True)
        lapstring = strops.lapstring(self.event['laps'])
        substr = ' '.join(
            (lapstring, self.event['distance'], self.event['rules'])).strip()
        sec.lines = []
        self._reslines = []
        ftime = None
        rcount = 0
        pcount = 0
        for r in self.riders:
            rcount += 1
            rno = r[COL_NO]
            rh = self.meet.rdb.get_rider(rno, self.series)
            if rh is None:
                self.meet.rdb.add_empty(bib, self.series)
                rh = self.meet.rdb.get_rider(bib, self.series)
            plink = ''
            rank = None
            rname = rh.resname()
            rcls = rh['class']
            rnat = rh['nation']
            # TODO: PARA Pilot
            #if rh.in_cat('tandem') and rh['note']:
            #ph = self.meet.rdb.get_rider(rh['note'], self.series)
            #if ph is not None:
            #plink = [
            #'', '',
            #ph.resname() + ' - Pilot', ph['class'], '', '', ''
            #]
            rtime = None
            rtod = None
            dtime = None
            dtod = None
            if self.onestart:
                pls = r[COL_PLACE]
                if pls:
                    if pls.isdigit():
                        rank = pls + '.'
                    else:
                        rank = pls
                    pcount += 1
                if r[COL_FINISH] is not None:
                    time = (r[COL_FINISH] - r[COL_START]).truncate(3)
                    rtod = time
                    if ftime is None:
                        ftime = time
                    else:
                        dtod = time - ftime
                        dtime = '+' + dtod.rawtime(2)

                    if r[COL_START] != tod.ZERO:
                        rtime = time.rawtime(3)
                    else:
                        rtime = time.rawtime(2) + '\u2007'

            if rank:
                sec.lines.append([rank, rno, rname, rcls, rtime, dtime, plink])
                finriders.add(rno)
                self._reslines.append({
                    'rank': pcount,
                    'class': rank,
                    'competitor': rno,
                    'nation': rnat,
                    'name': rname,
                    'info': rcls,
                    'result': rtime,
                    'extra': dtime,
                })

        doheats = False
        sv = []
        if substr:
            sv.append(substr)
        if self.onestart:
            if rcount > 0 and pcount < rcount:
                sv.append('STANDINGS')
                doheats = True
            else:
                sv.append('Result')
        sec.subheading = ' - '.join(sv)

        ret.append(sec)

        if doheats:
            for s in slist:
                if s.sectionid == secid:  # the startlist
                    newlines = []
                    for l in s.lines:
                        if l[1] not in finriders:
                            newlines.append(l)
                    s.lines = newlines
                    if s.lines:
                        s.heading = None
                        s.subheading = 'STARTLIST'
                        ret.append(s)

        if len(self.decisions) > 0:
            ret.append(self.meet.decision_section(self.decisions))
        return ret

    def editent_cb(self, entry, col):
        """Shared event entry update callback."""
        if col == 'pref':
            self.event['pref'] = entry.get_text()
        elif col == 'info':
            self.event['info'] = entry.get_text()

    def update_expander_lbl_cb(self):
        """Update event info expander label."""
        self.info_expand.set_label(self.meet.infoline(self.event))

    def clear_rank(self, cb):
        """Run callback once in main loop idle handler."""
        cb('')
        return False

    def clear_splitrank(self, label=None):
        """Clear time, rank, down and label"""
        if label == self._labelA:
            self._timeA = None
            self._labelA = None
            self._downA = None
            self._rankA = None
        self.resend_current()
        return False

    def split_trig(self, sp, t):
        """Register lap trigger."""
        bib = sp.getrider()
        elap = (t - self.curstart).truncate(3)
        self.splits.insert(elap, None, bib)
        rank = self.splits.rank(bib)  # 0-based rank
        self.log_split(sp.getrider(), self.curstart, t)
        sp.intermed(t, 2)  # show split... delay ~2 sec
        self._startA = self.curstart  # if not already entered
        self._labelA = self._splitlabel
        self._timeA = elap
        self._rankA = rank + 1
        self._downA = None
        if len(self.splits) > 1:
            # show a down/up time
            if rank == 0:  # leader
                nt = tod.agg(elap)
                ot = self.splits[1][0]
                self._downA = (nt - ot).truncate(2)
            else:
                ot = self.splits[0][0]
                self._downA = (elap - ot).truncate(2)
            GLib.timeout_add(3500, self.clear_splitrank, self._splitlabel)

        if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
            sid = '100m'
            if self.evtype == 'flying lap':
                sid = '200m'
            if rank is not None:
                rlbl = '({}) {}:'.format(rank + 1, sid)
            else:
                rlbl = '{}:'.format(sid)
            self.meet.scbwin.setr1(rlbl)
            GLib.timeout_add_seconds(2, self.clear_rank,
                                     self.meet.scbwin.setr1)
            self.meet.txt_postxt(
                5, 8,
                strops.truncpad(rlbl, 17) + ' ' + sp.get_time())
        if self.autoarm:
            self.armfinish(sp)
        self.resend_current()

    def fin_trig(self, sp, t):
        """Register finish trigger."""
        sp.finish(t)
        ri = self._getiter(sp.getrider())
        split = sp.getsplit(0)
        if ri is not None:
            self.settimes(ri, self.curstart, t, split)
        else:
            _log.warning('Rider %r not in model, finish time not stored',
                         sp.getrider())
        place = self.riders.get_value(ri, COL_PLACE)
        elap = (t - self.curstart).truncate(3)
        self._startA = self.curstart
        self._endA = t
        self._labelA = self._lenlabel
        self._timeA = elap
        if place.isdigit():
            self._rankA = int(place)
        self._downA = None
        if len(self.results) > 1:
            # show a down/up time
            if self._rankA == 1:  # new leader
                nt = tod.agg(elap)
                ot = self.results[1][0]
                self._downA = (nt - ot).truncate(2)
            else:
                ot = self.results[0][0]
                self._downA = (elap - ot).truncate(2)
        if self._competitorA:
            self._competitorA['rank'] = self._rankA
            self._competitorA['class'] = '%d.' % (self._rankA, )
            self._competitorA['result'] = self._timeA.rawtime(3)
            if self._rankA > 1:
                self._competitorA['extra'] = '+' + self._downA.rawtime(2)

        self.log_elapsed(sp.getrider(), self.curstart, t, split)
        if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
            self.meet.scbwin.setr1('(' + place + ')')
            self.meet.scbwin.sett1(sp.get_time())
            dist = self.meet.get_distance(self.distance, self.units)
            if dist is not None:
                elap = t - self.curstart
                spstr = elap.speedstr(dist).strip()
                GLib.timeout_add_seconds(1, self.clear_200_ttb,
                                         self.meet.scbwin, 'Avg:',
                                         spstr.rjust(12))
            else:
                GLib.timeout_add_seconds(2, self.clear_200_ttb,
                                         self.meet.scbwin)
            self.meet.gemini.set_rank(place)
            self.meet.gemini.set_time((t - self.curstart).rawtime(2))
            self.meet.gemini.show_brt()

        # call for a delayed announce...
        GLib.idle_add(self.delayed_announce)
        self.meet.delayed_export()

        # set delay for next heat / end of event
        self.meet.delayimp('2.00')

    def recover_start(self):
        """Recover missed start time"""
        if self.timerstat in ('idle', 'armstart'):
            rt = self.meet.recover_time(self.chan_S)
            if rt is not None:
                # rt: (event, wallstart)
                if self.timerstat == 'idle':
                    self.toarmstart()
                if self.fs.status == 'armstart':
                    _log.info('Recovered start time: %s', rt[0].rawtime(3))
                    self.meet.main_timer.dearm(self.chan_S)
                    self.torunning(rt[0], rt[1])
                    GLib.idle_add(self.armfinish, self.fs, True)
                else:
                    _log.info('No competitor loaded - recover start skipped')
            else:
                _log.info('No recent start time to recover')
        else:
            _log.info('Unable to recover start')

    def timercb(self, e):
        """Handle a timer event."""
        chan = strops.chan2id(e.chan)
        if self.timerstat == 'armstart':
            if chan == self.chan_S:  # Start trig
                self.torunning(e)
                GLib.timeout_add_seconds(2, self.armfinish, self.fs, True)
        elif self.timerstat == 'running':
            if chan == self.chan_I:  # Intermediate
                stat = self.fs.getstatus()
                if stat == 'armint':
                    self.split_trig(self.fs, e)
                # else ignore spurious intermediate
            elif chan == self.chan_F:  # Finish
                stat = self.fs.getstatus()
                if stat in ['armfin', 'armint']:
                    self.fin_trig(self.fs, e)
        return False

    def timeout(self):
        """Update scoreboard and respond to timing events."""
        if not self.winopen:
            return False
        if self.fs.status in ['running', 'armint', 'armfin']:
            now = tod.now()
            self.fs.runtime(now - self.lstart)
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                self.meet.scbwin.sett1(self.fs.get_time())
                elapstr = (now - self.lstart).rawtime(1).rjust(4) + ' '
                self.meet.gemini.set_time(elapstr)
                self.meet.gemini.show_brt()
        return True

    def show_200_ttb(self, scb):
        """Display time to beat."""
        if len(self.results) > 0:
            scb.setr2('Fastest:')
            scb.sett2(self.results[0][0].timestr(3))
        return False

    def clear_200_ttb(self, scb, r2='', t2=''):
        """Clear time to beat."""
        scb.setr2(r2)
        scb.sett2(t2)
        return False

    def torunning(self, st, walltime=None):
        """Set timer running."""
        if self.fs.status == 'armstart':
            self.fs.start(st)
        self.curstart = st
        if walltime is not None:
            self.lstart = walltime
        else:
            self.lstart = tod.now()
        self.timerstat = 'running'
        self.onestart = True
        if self.autoarm:
            self.armsplit(self.fs)
        if self._weather is None:
            self._weather = self.meet.get_weather()
        GLib.idle_add(self.delayed_announce)  # required?
        if walltime is None and self.timerwin and type(
                self.meet.scbwin) is scbwin.scbtt:
            GLib.timeout_add_seconds(3, self.show_200_ttb, self.meet.scbwin)

    def clearplaces(self):
        """Clear rider places."""
        for r in self.riders:
            r[COL_PLACE] = ''

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

    def delrider(self, bib):
        # Issue warning if removed rider in result
        bib = bib.upper()
        if self.results.rank(bib) is not None:
            _log.warning('Removed rider %r was in event %r result', bib,
                         self.evno)
            self.splits.remove(bib)
            self.results.remove(bib)
            if bib in self.traces:
                del self.traces[bib]
        if 'fsbib' in self._winState and self._winState['fsbib'].upper(
        ) == bib:
            _log.warning('Removed rider %r in event %r timer', bib, self.evno)

        i = self._getiter(bib)
        if i is not None:
            self.riders.remove(i)

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
                self.splits.changeno(oldNo, newNo)
                self.results.changeno(oldNo, newNo)
                if oldNo in self.traces:
                    self.traces[newNo] = self.traces[oldNo]
                    del self.traces[oldNo]
                return True
        return False

    def addrider(self, bib='', info=None):
        """Add specified rider to race model."""
        bib = bib.upper()
        istr = ''
        if info is not None:
            istr = str(info)
        ri = self._getrider(bib)
        if ri is None:  # adding a new record
            nr = [bib, '', '', '', '', istr, '', None, None, None]
            dbr = self.meet.rdb.get_rider(bib, self.series)
            if dbr is not None:
                nr[COL_NAME] = dbr.listname()
            self.riders.append(nr)
        else:
            # rider exists in model, update the seed value
            ri[COL_SEED] = istr

    def _editseed_cb(self, cell, path, new_text, col):
        """Edit the rider seeding."""
        old_text = self.riders[path][col]
        if old_text != new_text:
            self.riders[path][col] = new_text

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

    def placexfer(self):
        """Transfer places into model."""
        self.finished = False
        self.clearplaces()
        self._detail = {}
        count = 0
        place = 1
        for t in self.results:
            bib = t[0].refid
            self._detail[bib] = {}
            detail = self._detail[bib]
            splitrank = 0
            srank = self.splits.rank(bib)
            if srank is not None:
                splitrank = srank + 1
            split = None
            if splitrank > 0:
                split = self.splits[splitrank - 1][0]
                detail[self._splitlen] = {
                    'label': self._splitlabel,
                    'rank': splitrank,
                    'elapsed': split,
                    'interval': split,
                    'points': None,
                }
            if t[0] > tod.FAKETIMES['max']:
                if t[0] == tod.FAKETIMES['rel']:
                    place = self.results.rank(bib) + 1
                    self.onestart = True
                elif t[0] == tod.FAKETIMES['abd']:
                    place = 'abd'
                elif t[0] == tod.FAKETIMES['dsq']:
                    place = 'dsq'
                elif t[0] == tod.FAKETIMES['dns']:
                    place = 'dns'
                elif t[0] == tod.FAKETIMES['dnf']:
                    place = 'dnf'
            else:
                place = self.results.rank(bib) + 1
                self.onestart = True
                interval = None
                if split is not None:
                    interval = t[0] - split
                detail[self._finlen] = {
                    'label': self._lenlabel,
                    'rank': place,
                    'elapsed': t[0],
                    'interval': interval,
                    'points': None,
                }
            i = self._getiter(bib)
            if i is not None:
                if place == 'comment':  # superfluous but ok
                    place = self.riders.get_value(i, COL_COMMENT)
                self.riders.set_value(i, COL_PLACE, str(place))
                self.riders.swap(self.riders.get_iter(count), i)
                count += 1
            else:
                _log.warning('Rider %r not found in model, check places', bib)
        tcount = len(self.riders)
        self._standingstr = ''
        self._status = None
        if tcount > 0 and count > 0:
            if tcount == count:
                self._standingstr = 'Result'
                self.finished = True
                self._status = 'provisional'
            else:
                self._standingstr = 'Virtual Standing'
                self._status = 'virtual'

    def settimes(self,
                 iter,
                 st=None,
                 ft=None,
                 split=None,
                 doplaces=True,
                 comment=None):
        """Transfer race times into rider model."""
        bib = self.riders.get_value(iter, COL_NO)
        # clear result for this bib
        self.results.remove(bib)
        self.splits.remove(bib)
        # assign tods
        self.riders.set_value(iter, COL_START, st)
        self.riders.set_value(iter, COL_FINISH, ft)
        self.riders.set_value(iter, COL_100, split)
        # save result
        if st is None:
            st = tod.ZERO
        if ft is not None:
            last100 = None
            if split is not None:
                stime = (split - st).truncate(3)
                self.splits.insert(stime, None, bib)  # save first 100 split
                last100 = (ft - split).truncate(3)  # and prepare last 100
            elap = (ft - st).truncate(3)
            self.results.insert(elap, last100, bib)
        else:  # DNF/etc
            self.results.insert(comment, None, bib)
        # copy annotation into model if provided, or clear
        if comment:
            self.riders.set_value(iter, COL_COMMENT, comment)
        else:
            self.riders.set_value(iter, COL_COMMENT, '')
        # if reqd, do places
        if doplaces:
            self.placexfer()

    def armstart(self):
        """Arm timer for start trigger."""
        if self.timerstat == 'armstart':
            self.toload()
        elif self.timerstat in ['load', 'idle']:
            self.toarmstart()

    def armsplit(self, sp):
        """Arm timer for a split."""
        if self.timerstat == 'running':
            if sp.getstatus() == 'running':
                sp.toarmint('100m Armed')
                self.meet.main_timer.arm(self.chan_I)
            elif sp.getstatus() == 'armint':
                sp.torunning()
                self.meet.main_timer.dearm(self.chan_I)
                self.meet.main_timer.dearm(self.chan_F)
        return False

    def abortrider(self, sp):
        """Abort the current heat."""
        if sp.getstatus() not in ['idle', 'finish']:
            bib = sp.getrider()
            ri = self._getiter(bib)
            if ri is not None:
                self.settimes(ri, st=self.curstart, comment='dnf')
            sp.tofinish()
            self.meet.timer_log_msg(bib, '- Abort -')
            GLib.idle_add(self.delayed_announce)

    def falsestart(self):
        """Register false start."""
        if self.timerstat == 'running':
            if self.fs.getstatus() not in ['idle', 'finish']:
                self.fs.toload()
                bib = self.fs.getrider()
                self.meet.timer_log_msg(self.fs.getrider(), '- False start -')
                if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                    self.meet.scbwin.setr1('False')
                    self.meet.scbwin.sett1('Start')
            self.toidle(idletimers=False)
        elif self.timerstat == 'armstart':
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtt:
                self.meet.scbwin.sett1('            ')
                self.meet.scbwin.sett2('            ')
            self.toload()

    def armfinish(self, sp, force=False):
        """Arm timer for finish trigger."""
        if self.timerstat == 'running':
            if sp.getstatus() in ['running', 'finish']:
                if sp.getstatus() == 'finish':
                    self.meet.timer_log_msg(sp.getrider(), '- False Finish -')
                    self.meet.scbwin.setr1('')
                    self.meet.scbwin.setr2('')
                sp.toarmfin()
                self.meet.main_timer.arm(self.chan_F)
            elif sp.getstatus() == 'armfin' and not force:
                sp.torunning()
                self.meet.main_timer.dearm(self.chan_F)
            else:
                # request to arm finish before intermediate
                self.meet.main_timer.arm(self.chan_F)
        return False

    def toload(self):
        """Set timer status to load."""
        if self.fs.status == 'armstart':
            self.fs.toload()
        self.toidle(idletimers=False)

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

    def fmtridername(self, tp):
        """Prepare rider name for display on scoreboard."""
        name_w = self.meet.scb.linelen - 9
        bib = tp.getrider().strip()
        if bib != '':
            name = ''
            club = ''
            r = self._getrider(bib)
            if r is not None and r[COL_NO]:
                name, club, cls = self._getname(r[COL_NO], width=name_w)
                if not cls and len(club) == 3:
                    cls = club
            coldesc = ((3, 'r'), ' ', (name_w, 'l'), (5, 'r'))
            row = (r[COL_NO], name, cls)
            return scbwin.fmt_row(coldesc, row)
        else:
            return ''

    def showtimerwin(self):
        """Show timer window on scoreboard."""
        self.meet.scbwin = None
        self.meet.scbwin = scbwin.scbtt(self.meet.scb,
                                        self.meet.racenamecat(self.event),
                                        self.fmtridername(self.fs))
        self.meet.gemini.reset_fields()
        self.meet.gemini.set_bib(self.fs.getrider())
        self.meet.gemini.show_brt()
        self.timerwin = True
        self.meet.scbwin.reset()

    def toarmstart(self):
        """Set timer to arm start."""
        if self.fs.status == 'load':
            self.meet.timer_log_event(self.event)
            self.fs.toarmstart()
            self.timerstat = 'armstart'
            self.curstart = None
            self.lstart = None
            self.meet.main_timer.arm(self.chan_S)
            self.showtimerwin()
            self.meet.delayimp('0.01')
            if self.fs.status == 'armstart':
                bib = self.fs.getrider()
                if bib not in self.traces:
                    self.traces[bib] = []
                self.fslog = uiutil.traceHandler(self.traces[bib])
                logging.getLogger().addHandler(self.fslog)
                self.meet.scbwin.sett1('       0.0     ')
                nstr = self.fs.biblbl.get_text()
                self.meet.timer_log_msg(bib, nstr)
                self.meet.timer_log_env()
                self.meet.gemini.set_bib(bib)
                self.meet.gemini.set_time(' 0.0 ')
                self.meet.gemini.set_rank('')
                self.meet.gemini.show_brt()
            GLib.idle_add(self.delayed_announce)

    def toidle(self, idletimers=True):
        """Set timer to idle state."""
        if self.fslog is not None:
            logging.getLogger().removeHandler(self.fslog)
            self.fslog = None
        if idletimers:
            self.fs.toidle()
            self._competitorA = None
        self.timerstat = 'idle'
        self.meet.delayimp('2.00')
        self.curstart = None
        self.lstart = None
        for i in range(0, 8):
            self.meet.main_timer.dearm(i)
        if not self.onestart:
            pass
        self.fs.grab_focus()
        self._labelA = None
        self._timeA = None
        self._downA = None
        self._rankA = None
        self._startA = None
        self._endA = None

    def lanelookup(self, bib=None):
        """Prepare name string for timer lane."""
        r = self._getrider(bib)
        if r is None:
            if self.meet.get_clubmode():  # fill in starters
                _log.warning('Adding non-starter %r', bib)
                self.addrider(bib)
                r = self._getrider(bib)
            else:
                _log.warning('Rider %r not in event', bib)
                return None
        rtxt = '[New Rider]'
        if r is not None:
            rtxt = r[COL_NAME]
        return rtxt

    def _set_competitor(self, bib=None):
        """Update data bridge name fields for current object"""
        if bib is None:
            self._competitorA = None
            return

        rno = bib
        rname = None
        rnat = None
        rcls = None
        rh = self.meet.rdb.get_rider(bib, self.series)
        if rh is not None:
            rno = rh['no']
            rname = rh.resname()
            rnat = rh['nation']
            rcls = rh['class']
        self._competitorA = {
            'rank': None,
            'class': None,
            'competitor': rno,
            'nation': rnat,
            'name': rname,
            'info': rcls,
            'result': None,
            'extra': None,
        }

    def bibent_cb(self, entry, tp):
        """Bib entry callback."""
        bib = entry.get_text().strip().upper()
        if bib and bib.isalnum():
            nstr = self.lanelookup(bib)
            if nstr is not None:
                tp.biblbl.set_text(nstr)
                if tp.status == 'idle':
                    tp.toload()
                if self.timerstat == 'running':
                    tp.start(self.curstart)
                self._set_competitor(bib)
            else:
                _log.warning('Rider %r not in event.', bib)
                tp.toidle()
        else:
            tp.toidle()
            self._set_competitor()

    def treeview_button_press(self, treeview, event):
        """Set callback for mouse press on model view."""
        if event.button == 3:
            pathinfo = treeview.get_path_at_pos(int(event.x), int(event.y))
            if pathinfo is not None:
                path, col, cellx, celly = pathinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, False)
                self.context_menu.popup_at_pointer(None)
                return True
        return False

    def tod_context_clear_activate_cb(self, menuitem, data=None):
        """Clear times for selected rider."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            self.settimes(sel[1])
            self.log_clear(self.riders.get_value(sel[1], COL_NO))
            GLib.idle_add(self.delayed_announce)

    def tod_context_abd_activate_cb(self, menuitem, data=None):
        """Abandon rider."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            self.settimes(sel[1], comment='abd')
            GLib.idle_add(self.delayed_announce)

    def tod_context_rel_activate_cb(self, menuitem, data=None):
        """Relegate rider."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            self.settimes(sel[1], comment='rel')
            GLib.idle_add(self.delayed_announce)

    def tod_context_ntr_activate_cb(self, menuitem, data=None):
        """No time recorded for rider."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            self.settimes(sel[1], comment='ntr')
            GLib.idle_add(self.delayed_announce)

    def tod_context_dnf_activate_cb(self, menuitem, data=None):
        """DNF rider."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            self.settimes(sel[1], comment='dnf')
            GLib.idle_add(self.delayed_announce)

    def tod_context_dsq_activate_cb(self, menuitem, data=None):
        """Disqualify rider."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            self.settimes(sel[1], comment='dsq')
            GLib.idle_add(self.delayed_announce)

    def tod_context_dns_activate_cb(self, menuitem, data=None):
        """Rider did not start."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            self.settimes(sel[1], comment='dns')
            GLib.idle_add(self.delayed_announce)

    def tod_context_print_activate_cb(self, menuitem, data=None):
        """Print Rider trace"""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            bib = self.riders.get_value(sel[1], COL_NO)
            if bib in self.traces:
                secid = 'trace-' + str(bib).translate(strops.WEBFILE_UTRANS)
                sec = report.preformat_text(secid)
                sec.nobreak = True
                sec.lines = self.traces[bib]
                self.meet.print_report([sec], 'Timing Trace')

    def now_button_clicked_cb(self, button, entry=None):
        """Set specified entry to the current time."""
        if entry is not None:
            entry.set_text(tod.now().timestr())

    def tod_context_edit_activate_cb(self, menuitem, data=None):
        """Run edit time dialog."""
        sel = self.view.get_selection().get_selected()
        if sel is None:
            return False

        i = sel[1]
        lr = Gtk.TreeModelRow(self.riders, i)
        namestr = lr[COL_NO]
        dbr = self.meet.rdb.get_rider(lr[COL_NO], self.series)
        if dbr is not None:
            namestr = dbr.resname_bib()
        placestr = ''
        placeopts = {
            '': ' Not yet classified',
            'ntr': 'No time recorded',
            'dns': 'Did not start',
            'otl': 'Outside time limit',
            'dnf': 'Did not finish',
            'dsq': 'Disqualified',
        }
        if lr[COL_PLACE] and lr[COL_PLACE] not in placeopts:
            placestr = 'Ranked ' + strops.rank2ord(lr[COL_PLACE])
            if lr[COL_COMMENT]:
                placestr += ' (' + lr[COL_COMMENT] + ')'
        elif lr[COL_PLACE] in placeopts:
            placestr = placeopts[lr[COL_PLACE]]
        else:
            placestr = placeopts['']

        sections = {
            'result': {
                'object': None,
                'title': 'result',
                'schema': {
                    'title': {
                        'prompt': namestr,
                        'control': 'section',
                    },
                    'class': {
                        'prompt': 'Classification:',
                        'hint': 'Rider classification for event',
                        'control': 'label',
                        'value': placestr,
                    },
                    'start': {
                        'prompt': 'Start:',
                        'hint': 'Recorded start time',
                        'type': 'tod',
                        'places': 4,
                        'value': lr[COL_START],
                        'nowbut': True,
                        'control': 'short',
                        'subtext': 'Set start time to now',
                        'index': COL_START,
                    },
                    'finish': {
                        'prompt': 'Finish:',
                        'hint': 'Recorded finish time',
                        'type': 'tod',
                        'places': 4,
                        'value': lr[COL_FINISH],
                        'nowbut': True,
                        'control': 'short',
                        'subtext': 'Set finish time to now',
                        'index': COL_FINISH,
                    },
                },
            },
        }
        res = uiutil.options_dlg(window=self.meet.window,
                                 title='Edit times',
                                 sections=sections)
        changed = False
        dotimes = False
        for option in res['result']:
            if res['result'][option][0]:
                changed = True
                if 'index' in sections['result']['schema'][option]:
                    index = sections['result']['schema'][option]['index']
                    lr[index] = res['result'][option][2]
                    _log.debug('Updated %s to: %r', option,
                               res['result'][option][2])
                    if option in ('start', 'finish'):
                        dotimes = True
                else:
                    _log.debug('Unknown option %r changed', option)
        if dotimes:
            bib = lr[COL_NO]
            stod = lr[COL_START]
            ftod = lr[COL_FINISH]
            if stod is not None and ftod is not None:
                self.settimes(i, stod, ftod)
                self.log_elapsed(bib, stod, ftod, manual=True)
            else:
                self.settimes(i)
                self.log_clear(bib)
            _log.info('Race times manually adjusted for rider %r', bib)
            GLib.idle_add(self.delayed_announce)

    def tod_context_del_activate_cb(self, menuitem, data=None):
        """Delete selected row from race model."""
        sel = self.view.get_selection().get_selected()
        if sel is not None:
            i = sel[1]  # grab off row iter
            self.riders.remove(i)
            GLib.idle_add(self.delayed_announce)

    def log_clear(self, bib):
        """Print clear time log."""
        self.meet.timer_log_msg(bib, '- Time Cleared -')

    def log_split(self, bib, start, split):
        """Print split log."""
        slbl = '100m'
        if self.evtype == 'flying lap':
            slbl = 'int'
        self.meet.timer_log_straight(bib, slbl, split - start, 3)

    def log_elapsed(self, bib, start, finish, split=None, manual=False):
        """Print elapsed log info."""
        if manual:
            self.meet.timer_log_msg(bib, '- Manual Adjust -')
        self.meet.timer_log_straight(bib, 'ST', start)
        self.meet.timer_log_straight(bib, 'FIN', finish)
        if split is not None:
            slbl = 'L100'
            if self.evtype == 'flying lap':
                slbl = 'L200'
            self.meet.timer_log_straight(bib, slbl, finish - split, 3)
        self.meet.timer_log_straight(bib, 'TIME', finish - start, 3)

    def show(self):
        """Show race window."""
        self.frame.show()

    def hide(self):
        """Hide race window."""
        self.frame.hide()

    def __init__(self, meet, event, ui=True):
        """Constructor."""
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
        self.decisions = []

        # properties
        self.distance = 200
        self.units = 'metres'
        self.autoarm = True
        self.chan_S = 4
        self.chan_I = 5
        self.chan_F = 1

        # race run time attributes
        self.onestart = False
        self.winopen = ui
        self.timerwin = False
        self.timerstat = 'idle'
        self.curstart = None
        self.lstart = None
        self.results = tod.todlist('FIN')
        self.splits = tod.todlist('100')
        self.inomnium = False
        self.seedsrc = 1  # default seeding is by rank in last round
        self.finished = False
        self._standingstr = ''
        self.context_menu = None
        self.traces = {}
        self._winState = {}  # cache ui settings for headless load/save
        self._status = None
        self._startlines = None
        self._reslines = None
        self._detail = None
        self._infoLine = None
        self._competitorA = None
        self._labelA = None
        self._timeA = None
        self._downA = None
        self._rankA = None
        self._startA = None
        self._endA = None
        self._splitlabel = None
        self._splitlen = None
        self._finlen = None
        self._lenlabel = None
        self._weather = None

        self.riders = Gtk.ListStore(
            str,  # 0 bib
            str,  # 1 name
            str,  # 2 reserved
            str,  # 3 reserved
            str,  # 4 Comment
            str,  # 5 seed
            str,  # 6 place
            object,  # 7 Start
            object,  # 8 Finish
            object)  # 9 100m

        self._splitlabel = '100\u2006m'
        self._splitlen = '100'
        self._finlen = '200'
        self._lenlabel = '200\u2006m'
        tmlbl = '200m/L100m'
        if self.evtype == 'flying lap':
            tmlbl = 'Time/L200m'
            self._splitlabel = '-200\u2006m'  # this should be config'd
            self._splitlen = '-200'  # this should be config'd
            self._finlen = 'lap'
            self._lenlabel = 'Lap'

        # show window
        if ui:
            b = uiutil.builder('ittt.ui')
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

            # Timer Pane
            mf = b.get_object('race_timer_pane')
            self.fs = uiutil.timerpane('Timer', doser=False)
            self.fs.bibent.connect('activate', self.bibent_cb, self.fs)
            self.fs.hide_splits()
            self.fs.splitlbls = ['100\u2006m Split', 'Finish']
            self.fslog = None
            mf.pack_start(self.fs.frame, True, True, 0)

            # riders pane
            t = Gtk.TreeView(self.riders)
            self.view = t
            t.set_reorderable(True)
            t.set_enable_search(False)
            t.set_rules_hint(True)
            t.connect('button_press_event', self.treeview_button_press)

            uiutil.mkviewcoltxt(t, 'No.', COL_NO, calign=1.0)
            uiutil.mkviewcoltxt(t,
                                'Name',
                                COL_NAME,
                                self._editname_cb,
                                expand=True)
            uiutil.mkviewcoltxt(t, 'Seed', COL_SEED, self._editseed_cb)
            uiutil.mkviewcoltod(t, tmlbl, cb=self.todstr)
            uiutil.mkviewcoltxt(t, 'Rank', COL_PLACE, halign=0.5, calign=0.5)
            t.show()
            b.get_object('race_result_win').add(t)
            self.context_menu = b.get_object('rider_context')
            b.connect_signals(self)
