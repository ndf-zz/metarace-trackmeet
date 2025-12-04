# SPDX-License-Identifier: MIT
"""Sprint round handler for trackmeet."""

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

_log = logging.getLogger('sprnd')
_log.setLevel(logging.DEBUG)

# config version string
EVENT_ID = 'sprnd-2.1'

# race gobject model column constants
COL_CONTEST = 0  # contest ID '1v16'
COL_A_NO = 1  # Number of A rider
COL_A_STR = 2  # Namestr of A rider
COL_A_PLACE = 3  # Place string of A rider
COL_B_NO = 4  # Number of B rider
COL_B_STR = 5  # Namestr of B rider
COL_B_PLACE = 6  # Place string of B rider
COL_200M = 7  # time for last 200m
COL_WINNER = 8  # no of 'winner'
COL_COMMENT = 9  # reserved - unused
COL_A_QUAL = 10  # Qualifying time of A rider
COL_B_QUAL = 11  # Qualifying time of B rider
COL_BYE = 12  # BYE Flag

# scb function key mappings
key_startlist = 'F3'  # show starters in table
key_results = 'F4'  # recalc/show result window

# timing function key mappings
key_armstart = 'F5'  # arm for start/200m impulse
key_showtimer = 'F6'  # show timer
key_armfinish = 'F9'  # arm for finish impulse
key_win_a = 'F11'  # A rider wins
key_win_b = 'F12'  # B rider wins

# extended function key mappings
key_abort = 'F5'  # + ctrl for clear/abort
key_walk_a = 'F9'  # + ctrl for walk over
key_walk_b = 'F10'
key_rel_a = 'F11'  # + ctrl for relegation
key_rel_b = 'F12'

# Pre-defined "standard" power of 2 contests
_STD_CONTESTS = {
    1: ('bye', ),
    2: ('1v2', ),
    3: ('bye', '2v3'),
    4: ('1v4', '2v3'),
    5: ('bye', 'bye', 'bye', '4v5'),
    6: ('bye', 'bye', '3v6', '4v5'),
    7: ('bye', '2v7', '3v6', '4v5'),
    8: ('1v8', '2v7', '3v6', '4v5'),
    9: ('bye', 'bye', 'bye', 'bye', 'bye', 'bye', 'bye', '8v9'),
    10: ('bye', 'bye', 'bye', 'bye', 'bye', 'bye', '7v10', '8v9'),
    11: ('bye', 'bye', 'bye', 'bye', 'bye', '6v11', '7v10', '8v9'),
    12: ('bye', 'bye', 'bye', 'bye', '5v12', '6v11', '7v10', '8v9'),
    13: ('bye', 'bye', 'bye', '4v13', '5v12', '6v11', '7v10', '8v9'),
    14: ('bye', 'bye', '3v14', '4v13', '5v12', '6v11', '7v10', '8v9'),
    15: ('bye', '2v15', '3v14', '4v13', '5v12', '6v11', '7v10', '8v9'),
    16: ('1v16', '2v15', '3v14', '4v13', '5v12', '6v11', '7v10', '8v9'),
    # [3.2.050]
    28: ('bye', 'bye', 'bye', 'bye', '5v28', '6v27', '7v26', '8v25', '9v24',
         '10v23', '11v22', '12v21', '13v20', '14v19', '15v18', '16v17'),
}

_CONFIG_SCHEMA = {
    'etype': {
        'prompt': 'Sprint Round/Final',
        'control': 'section',
    },
    'contests': {
        'prompt': 'Contests:',
        'hint': 'List of contests and byes',
        'default': '',
        'defer': True,
    },
    'otherstime': {
        'prompt': 'Losers:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Rank by 200m time?',
        'hint': 'Rank losers by qualifying time [3.2.050]',
        'defer': True,
    },
}


class sprnd:
    """Data handling for sprint rounds."""

    def force_running(self, start=None):
        """Ignore force start time."""
        self.meet.set_event_start(self.event)

    def show_lapscore(self, laps, prev):
        """Accept laps when idle/running"""
        ret = False
        if self.event['laps'] and prev is not None and laps is not None:
            if prev - laps == 1:  # only announce decrement
                if self.timerstat in ('idle', 'running'):
                    ret = True
        return ret

    def resend_current(self):
        fragment = self.event.get_fragment()
        if fragment:
            contest = None
            heat = None
            i = self.current_contest_combo.get_active_iter()
            if i is not None:
                cid = self.contests.get_value(i, COL_CONTEST)
                if self.event['type'] == 'sprint final':
                    contest = self.contestroot(cid)
                    heat = self.contestheat(cid)
                else:
                    contest = cid
            data = self.data_pack()
            if contest is not None:
                fragment = '/'.join((fragment, contest))
                data['subtitle'] = contest
            self.meet.db.sendCurrent(self.event, fragment, data)

    def data_pack(self):
        """Pack standard values for a current object"""
        ret = {}
        ret['competitionType'] = 'bunch'  # for all sprints
        ret['status'] = self._status
        ret['weather'] = self._weather
        if self._startlines is not None:
            ret['competitors'] = self._startlines
        if self._reslines is not None:
            ret['lines'] = self._reslines
        if self._infoLine is not None:
            ret['info'] = self._infoLine  # overrides rules
        if len(self.decisions) > 0:
            ret['decisions'] = self.meet.decision_list(self.decisions)
        return ret

    def data_bridge(self):
        """Export data bridge fragments, startlists and results"""
        fragment = self.event.get_fragment()
        if fragment:
            # pre-load event data
            data = self.data_pack()

            # work out if competition, phase or contest
            path = fragment.split('/')
            pathlen = len(path)
            subtype = None
            if pathlen == 2:  # competition
                subtype = 'phases'
            elif pathlen == 3:  # phase
                subtype = 'contests'
            elif pathlan == 4:  # contest
                subtype = 'heats'
                # in the case of final - this should not be possible
            data[subtype] = {}  # in parent fragment
            for cid, contest in self._sprintres.items(
            ):  # visit filled contests
                # add the label entry
                data[subtype][cid] = contest['subtitle']
                if self.event['type'] == 'sprint final':
                    _log.debug('TODO: expand heats of contests')
                else:  # single-heat contests
                    subdata = {
                        'competitionType': 'bunch',
                        'subtitle': contest['subtitle'],
                        'status': contest['status'],
                    }
                    if contest['lines']:
                        subdata['lines'] = contest['lines']
                    if contest['competitors']:
                        subdata['competitors'] = contest['competitors']

                    # duplicate weather from event
                    if 'weather' in data:
                        subdata['weather'] = data['weather']

                    # publish inter to bridge
                    subfrag = '/'.join((fragment, cid))
                    self.meet.db.updateFragment(self.event, subfrag, subdata)
            _log.debug('Write main object %s with data=%r', fragment, data)
            self.meet.db.updateFragment(self.event, fragment, data)

    def ridercb(self, rider):
        """Rider change notification"""
        if self.winopen:
            if rider is not None:
                rno = rider[0]
                series = rider[1]
                if series == self.series:
                    dbr = self.meet.rdb[rider]
                    for cr in self.contests:
                        if cr[COL_A_NO] == rno:
                            cr[COL_A_STR] = dbr.listname()
                        elif cr[COL_B_NO] == rno:
                            cr[COL_B_STR] = dbr.listname()
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

    def standingstr(self, width=None):
        """Return an event status string for reports and scb."""
        self._standingstat = ''
        self._status = None
        self._rescache = {}
        self.finished = False
        ccount = 0
        dcount = 0
        self._sprintres = {}
        # !!! collect and update all the subfrag results here
        if self.event['type'] == 'sprint final':
            ## TODO: sprint res includes heats
            # re-build the result cache
            for cr in self.contests:
                cid = self.contestroot(cr[COL_CONTEST])
                heat = self.contestheat(cr[COL_CONTEST])
                if cid not in self._rescache:
                    aqual = None
                    if cr[COL_A_QUAL] is not None:
                        aqual = cr[COL_A_QUAL].rawtime(2)
                    bqual = None
                    if cr[COL_B_QUAL] is not None:
                        bqual = cr[COL_B_QUAL].rawtime(2)
                    self._rescache[cid] = {
                        'a': 0,
                        'b': 0,
                        'bye': cr[COL_BYE],
                        'ano': cr[COL_A_NO],
                        'bno': cr[COL_B_NO],
                        'aname': cr[COL_A_STR],
                        'bname': cr[COL_B_STR],
                        'aqual': aqual,
                        'bqual': bqual,
                        'ares': {
                            '1': None,
                            '2': None,
                            '3': None
                        },
                        'bres': {
                            '1': None,
                            '2': None,
                            '3': None
                        }
                    }
                if cr[COL_WINNER]:
                    # heat has a winner
                    if cr[COL_WINNER] == cr[COL_A_NO]:
                        self._rescache[cid]['a'] += 1
                        if cr[COL_200M] is not None:
                            self._rescache[cid]['ares'][heat] = cr[
                                COL_200M].rawtime(2)
                        else:
                            self._rescache[cid]['ares'][heat] = 'win'
                    else:
                        self._rescache[cid]['b'] += 1
                        if cr[COL_200M] is not None:
                            self._rescache[cid]['bres'][heat] = cr[
                                COL_200M].rawtime(2)
                        else:
                            self._rescache[cid]['bres'][heat] = 'win'
            # count up resolved contests
            ccount = len(self._rescache)
            for cid in self._rescache:
                cm = self._rescache[cid]
                if cm['bye']:
                    ccount -= 1  # one less contest result required
                elif max(cm['a'], cm['b']) > 1:
                    dcount += 1  # this contest is decided
        else:
            # visit all contests simply
            ccount = len(self.contests)
            for c in self.contests:
                cid = self.contestroot(c[COL_CONTEST])
                self._sprintres[cid] = {
                    'subtitle': cid,
                    'status': None,
                    'competitors': [],
                    'lines': [],
                }
                subres = self._sprintres[cid]
                acompetitor = {}
                bcompetitor = {}
                aresult = {}
                bresult = {}
                if c[COL_A_NO] and c[COL_A_NO].strip():
                    acompetitor['competitor'] = c[COL_A_NO]
                    self._fill_competitor(acompetitor)
                    subres['competitors'].append(acompetitor)
                    for k in acompetitor:
                        aresult[k] = acompetitor[k]
                if c[COL_B_NO] and c[COL_B_NO].strip():
                    bcompetitor['competitor'] = c[COL_B_NO]
                    self._fill_competitor(bcompetitor)
                    subres['competitors'].append(bcompetitor)
                    for k in bcompetitor:
                        bresult[k] = bcompetitor[k]
                if c[COL_A_QUAL] is not None:
                    ## data type?
                    acompetitor['qualTime'] = c[COL_A_QUAL]
                    _log.debug('Qual type is: %r', c[COL_A_QUAL])
                if c[COL_B_QUAL] is not None:
                    ## data type?
                    bcompetitor['qualTime'] = c[COL_B_QUAL]

                if c[COL_BYE]:
                    ccount -= 1  # one less contest result required
                    aresult['rank'] = 1
                    aresult['class'] = '1.'
                    aresult['result'] = 'bye'
                    subres['lines'].append(aresult)
                    subres['status'] = 'provisional'
                elif c[COL_WINNER]:
                    dcount += 1
                    # contest has a winner
                    result = None
                    if c[COL_200M] is not None:
                        result = c[COL_200M].rawtime(2)
                    subres['status'] = 'provisional'
                    if c[COL_WINNER] == c[COL_A_NO]:
                        aresult['rank'] = 1
                        aresult['class'] = '1.'
                        aresult['result'] = result
                        bresult['rank'] = 2
                        bresult['class'] = '2.'
                        subres['lines'].append(aresult)
                        subres['lines'].append(bresult)
                    else:
                        bresult['rank'] = 1
                        bresult['class'] = '1.'
                        bresult['result'] = result
                        aresult['rank'] = 2
                        aresult['class'] = '2.'
                        subres['lines'].append(bresult)
                        subres['lines'].append(aresult)
        if ccount > 0:
            if dcount:
                if ccount == dcount:
                    self._standingstat = 'Result'
                    self.finished = True
                    self._status = 'provisional'
                else:
                    self._status = 'virtual'  # contests have sub status
                    if self.event['type'] == 'sprint final':
                        self._standingstat = 'Virtual Standing'
                    else:
                        self._standingstat = 'Provisional Result'
        #_log.debug('ccount=%d, dcount=%d, finished=%r, str=%s',
        # ccount, dcount, self.finished, self._standingstat)
        return self._standingstat

    def ismedalphase(self):
        ret = False
        if len(self.contestlist) == 2:
            if self.contestlist[0].lower() == 'bronze':
                if self.contestlist[1].lower() == 'gold':
                    ret = True
        return ret

    def addrider(self, bib='', info=None):
        """Add specified rider to race model."""
        bib = bib.upper()
        qual = tod.mktod(info)
        rname = self._listname(bib)
        if self.event['type'] == 'sprint final':
            slot = None
            afound = False
            cstack = []
            for cr in self.contests:
                # check for 'first' empty slot in A riders
                cid = self.contestroot(cr[COL_CONTEST])
                if slot is None:
                    if cr[COL_A_NO] == '':
                        slot = cid
                        afound = True
                if slot is not None and slot == cid:
                    cr[COL_A_NO] = bib
                    cr[COL_A_STR] = rname
                    cr[COL_A_PLACE] = ''  # LOAD?
                    cr[COL_A_QUAL] = qual
                    ## special case the bye here
                    if cr[COL_BYE]:
                        cr[COL_A_PLACE] = ' '
                        cr[COL_B_STR] = ' '
                        cr[COL_B_PLACE] = ' '
                        cr[COL_B_NO] = ' '
                        cr[COL_WINNER] = bib  # auto win the bye rider
                elif afound:
                    # a slot was found, heats exhausted
                    return
                if not afound:
                    cstack.insert(0, cr)
            slot = None
            bfound = False
            if not afound:
                for cr in cstack:
                    # check for 'first' empty slot in B riders
                    cid = self.contestroot(cr[COL_CONTEST])
                    if slot is None:
                        if cr[COL_B_NO] == '':
                            slot = cid
                            bfound = True
                    if slot is not None and slot == cid:
                        cr[COL_B_NO] = bib
                        cr[COL_B_STR] = rname
                        cr[COL_B_PLACE] = ''  # LOAD?
                        cr[COL_B_QUAL] = qual
                    elif bfound:
                        # slot was found, heats exhausted
                        return
            if afound or bfound:
                return
        else:
            cstack = []
            for cr in self.contests:
                # check for 'first' empty slot in A riders
                if cr[COL_A_NO] == '':
                    cr[COL_A_NO] = bib
                    cr[COL_A_STR] = rname
                    cr[COL_A_PLACE] = ''  # LOAD?
                    cr[COL_A_QUAL] = qual
                    ## special case the bye here
                    if cr[COL_BYE]:
                        cr[COL_A_PLACE] = ' '
                        cr[COL_B_STR] = ' '
                        cr[COL_B_PLACE] = ' '
                        cr[COL_B_NO] = ' '
                        cr[COL_WINNER] = bib  # auto win the bye rider
                    return
                cstack.insert(0, cr)
            for cr in cstack:
                # reverse contests for B riders
                if cr[COL_B_NO] == '':
                    cr[COL_B_NO] = bib
                    cr[COL_B_STR] = rname
                    cr[COL_B_PLACE] = ''  # LOAD?
                    cr[COL_B_QUAL] = qual
                    return
        _log.warning('Not enough heats for the specified starters: %r', bib)

    def inevent(self, bib):
        """Return true if rider appears in model."""
        inEvent = False
        for c in self.contests:
            if c[COL_A_NO] == bib or c[COL_B_NO] == bib:
                inEvent = True
                break
        return inEvent

    def changerider(self, oldNo, newNo):
        """Update rider no in event"""
        oldNo = oldNo.upper()
        newNo = newNo.upper()
        if self.inevent(oldNo):
            if oldNo != newNo and not self.inevent(newNo):
                rname = self._listname(newNo)
                for c in self.contests:
                    if c[COL_A_NO] == oldNo:
                        c[COL_A_NO] = newNo
                        c[COL_A_STR] = rname
                    elif c[COL_B_NO] == oldNo:
                        c[COL_B_NO] = newNo
                        c[COL_B_STR] = rname
                return True
        return False

    def delrider(self, bib):
        """Remove specified rider from the model."""
        bib = bib.upper()
        inRes = False
        for c in self.contests:
            if c[COL_A_NO] == bib:
                c[COL_A_NO] = ''
                c[COL_A_PLACE] = ''
                c[COL_A_STR] = ''
            elif c[COL_B_NO] == bib:
                c[COL_B_NO] = ''
                c[COL_B_PLACE] = ''
                c[COL_B_STR] = ''
            if c[COL_WINNER] == bib:
                c[COL_200M] = None
                c[COL_WINNER] = ''
                inRes = True

        if inRes:
            _log.warning('Removed rider %r was in event %r result', bib,
                         self.evno)

    def reload_riders(self):
        self.del_riders()
        usespec = self.event['auto'].strip()
        evpart, tailpart = usespec.split(':', 1)
        if self.ismedalphase():
            # special case: assignment is 3,1,2,4
            if evpart in self.meet.edb and tailpart == '1-4':
                usespec = '%s:3,1,2,4' % (evpart, )
                _log.debug('Assigning riders for medal finals: %s', usespec)
        self.meet.autostart_riders(self, usespec, infocol=2)

    def loadconfig(self):
        """Load race config from disk."""
        self.contests.clear()
        def_otherstime = False
        if self.event['plac'] and self.event['plac'] > 4:
            def_otherstime = True

        cr = jsonconfig.config({
            'event': {
                'id': EVENT_ID,
                'contests': [],
                'timerstat': None,
                'showinfo': False,
                'otherstime': def_otherstime,
                'decisions': [],
                'weather': None,
            },
            'contests': {}
        })
        cr.add_section('event')
        cr.add_section('contests')
        if not cr.load(self.configfile):
            _log.info('%r not read, loading defaults', self.configfile)

        # event metas
        self._weather = cr.get('event', 'weather')
        self.decisions = cr.get('event', 'decisions')
        self.otherstime = cr.get_bool('event', 'otherstime', def_otherstime)
        self.onestart = False

        # read in contests and pre-populate standard cases
        contestlist = cr.get('event', 'contests')
        if not contestlist and self.event['plac']:
            # placeholders is set and contests are not
            if self.event['info'] == 'Final' and self.event['plac'] == 4:
                contestlist = ('Bronze', 'Gold')
            else:
                if self.event['plac'] in _STD_CONTESTS:
                    contestlist = _STD_CONTESTS[self.event['plac']]
        self.contestlist = contestlist

        # restore contest details
        oft = 0
        curactive = -1
        for cid in contestlist:
            bye = False
            if cid == 'bye':
                cid = str(oft + 1) + ' bye'
                bye = True
            elif 'bye' in cid:
                cid = cid.replace('-', ' ')
                bye = True  # Assume contest no is provided in text
            heats = (cid, )
            if self.event['type'] == 'sprint final':
                heats = (cid + ' Heat 1', cid + ' Heat 2', cid + ' Heat 3')
            for c in heats:
                if cr.has_option('contests', c):
                    res = cr.get('contests', c)
                    ft = tod.mktod(res[4])
                    if ft or res[5]:
                        self.onestart = True  # at least one run so far
                    else:
                        if curactive == -1:
                            curactive = oft
                    aqual = tod.mktod(res[7])
                    bqual = tod.mktod(res[8])
                    astr = self._listname(res[0])
                    bstr = self._listname(res[2])
                    nr = [
                        c, res[0], astr, res[1], res[2], bstr, res[3], ft,
                        res[5], res[6], aqual, bqual, bye
                    ]
                    self.add_contest(c, nr, bye=bye)
                else:
                    self.add_contest(c, bye=bye)
                oft += 1

        if not self.onestart and self.event['auto']:
            self.reload_riders()

        # update the standing status (like placexfer :/)
        self.standingstr()

        if self.winopen:
            self.update_expander_lbl_cb()
            self.info_expand.set_expanded(
                strops.confopt_bool(cr.get('event', 'showinfo')))
            self.current_contest_combo.set_active(curactive)
        else:
            self._winState['showinfo'] = cr.get('event', 'showinfo')

        # After load complete - check config and report.
        eid = cr.get('event', 'id')
        if eid and eid != EVENT_ID:
            _log.info('Event config mismatch: %r != %r', eid, EVENT_ID)

    def _resname(self, bib):
        ret = ''
        if bib.strip():
            ret = self._get_rider(bib).resname()
        return ret

    def _listname(self, bib):
        ret = ''
        if bib.strip():
            ret = self._get_rider(bib).fitname(32)
        return ret

    def _get_rider(self, bib):
        """Return rdb for the provided bib, or create a new empty one"""
        bib = bib.upper()
        dbr = self.meet.rdb.get_rider(bib, self.series)
        if dbr is None:
            self.meet.rdb.add_empty(bib, self.series)
            dbr = self.meet.rdb.get_rider(bib, self.series)
        return dbr

    def del_riders(self):
        """Remove all starters from model."""
        for c in self.contests:
            for col in [
                    COL_A_NO, COL_A_STR, COL_A_PLACE, COL_B_NO, COL_B_STR,
                    COL_B_PLACE, COL_WINNER
            ]:
                c[col] = ''
            c[COL_200M] = None
            c[COL_A_QUAL] = None
            c[COL_B_QUAL] = None

    def add_contest(self, c, cv=[], bye=False):
        if len(cv) == 13:
            self.contests.append(cv)
        else:
            # create new cv
            self.contests.append(
                [c, '', '', '', '', '', '', None, '', '', None, None, bye])

    def race_ctrl_action_activate_cb(self, entry, data=None):
        """Perform current action on bibs listed."""
        rlist = entry.get_text()
        acode = self.action_model.get_value(
            self.ctrl_action_combo.get_active_iter(), 1)
        if acode == 'add':
            rlist = strops.riderlist_split(rlist, self.meet.rdb, self.series)
            for bib in rlist:
                self.addrider(bib)
            entry.set_text('')
        elif acode == 'del':
            rlist = strops.riderlist_split(rlist, self.meet.rdb, self.series)
            for bib in rlist:
                self.delrider(bib)
            entry.set_text('')
        else:
            _log.error('Ignoring invalid action')
            return False
        self.standingstr()
        GLib.idle_add(self.delayed_announce)

    def startlist_report(self, program=False):
        """Return a startlist report."""
        ret = []
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        if self.event['type'] == 'sprint final':
            sec = report.sprintfinal(secid)
        else:
            sec = report.sprintround(secid)
        sec.nobreak = True
        headvec = self.event.get_info(showevno=True).split()
        if not program:
            headvec.append('Start List')
        sec.heading = ' '.join(headvec)

        lapstring = strops.lapstring(self.event['laps'])
        substr = ' '.join((
            lapstring,
            self.event['distance'],
            self.event['rules'],
        )).strip()
        if substr:
            sec.subheading = substr

        self._startlines = []
        self._conteststarts = {}
        cidset = set()
        for cr in self.contests:
            cid = self.contestroot(cr[COL_CONTEST])
            if cid not in cidset:
                self._conteststarts[cid] = []
                cidset.add(cid)
                byeflag = None

                ano = cr[COL_A_NO]
                rh = self._get_rider(ano)
                aname = rh.resname()
                anat = rh['nation']
                acls = rh['class']
                apilot = None
                ph = self.meet.rdb.get_pilot(rh)
                if ph is not None:
                    apilot = ph.resname()

                bno = cr[COL_B_NO]
                rh = self._get_rider(bno)
                bname = rh.resname()
                bnat = rh['nation']
                bcls = rh['class']
                bpilot = None
                ph = self.meet.rdb.get_pilot(rh)
                if ph is not None:
                    bpilot = ph.resname()

                aqual = None
                raqual = None
                if cr[COL_A_QUAL] is not None:
                    raqual = cr[COL_A_QUAL].truncate(2)
                    aqual = raqual.rawtime(2)
                bqual = None
                rbqual = None
                if cr[COL_B_QUAL] is not None:
                    rbqual = cr[COL_B_QUAL].truncate(2)
                    bqual = rbqual.rawtime(2)
                timestr = None
                byemark = None
                arobj = {
                    'competitor': ano,
                    'nation': anat,
                    'name': aname,
                    'pilot': apilot,
                    'info': acls,
                    'qualTime': raqual,
                }
                self._startlines.append(arobj)
                self._conteststarts[cid].append(arobj)
                if cr[COL_BYE]:
                    timestr = ' '
                    bno = ' '
                    bname = ' '
                    bqual = None
                    byeflag = ' '
                    byemark = ' '
                else:
                    brobj = {
                        'competitor': bno,
                        'nation': bnat,
                        'name': bname,
                        'pilot': bpilot,
                        'info': bcls,
                        'qualTime': rbqual,
                    }
                    self._startlines.append(brobj)
                    self._conteststarts[cid].append(brobj)

                if self.event['type'] == 'sprint final':
                    sec.lines.append([
                        cid + ':',
                        [None, ano, aname, aqual, None, None, None, None],
                        [None, bno, bname, bqual, None, None, None, None]
                    ])
                else:
                    sec.lines.append([
                        cr[COL_CONTEST] + ':', [None, ano, aname, aqual],
                        [byeflag, bno, bname, bqual], timestr
                    ])

        # Prizemoney line
        sec.prizes = self.meet.prizeline(self.event)

        # Footer line (with suppressed competitor count)
        sec.footer = self.meet.footerline(self.event)

        ret.append(sec)
        return ret

    def contestroot(self, cid):
        """Return the root contest for a head contest id"""
        return cid.split(' Heat ', 1)[0]

    def contestheat(self, cid):
        """Return the contest heat number for a contest id"""
        return cid.split(' Heat ', 1)[-1]

    def saveconfig(self):
        """Save race to disk."""
        if self.readonly:
            _log.error('Attempt to save readonly event')
            return
        cw = jsonconfig.config()
        cw.add_section('event')
        cw.add_section('contests')
        if self.winopen:
            cw.set('event', 'showinfo', self.info_expand.get_expanded())
        else:
            cw.set('event', 'showinfo', self._winState['showinfo'])
        cw.set('event', 'timerstat', self.timerstat)
        cw.set('event', 'decisions', self.decisions)
        cw.set('event', 'weather', self._weather)
        cw.set('event', 'otherstime', self.otherstime)
        contestset = set()
        contestlist = []
        for c in self.contests:
            # keep ordered list of root contests
            cid = c[COL_CONTEST]
            croot = cid
            if self.event['type'] == 'sprint final':
                croot = self.contestroot(cid)
            if croot not in contestset:
                contestset.add(croot)
                if c[COL_BYE]:
                    contestlist.append(croot.replace(' ', '-'))
                else:
                    contestlist.append(croot)

            cw.set('contests', cid, [
                c[COL_A_NO], c[COL_A_PLACE], c[COL_B_NO], c[COL_B_PLACE],
                c[COL_200M], c[COL_WINNER], c[COL_COMMENT], c[COL_A_QUAL],
                c[COL_B_QUAL]
            ])
        # TODO: Handle mismatch of list and map
        cw.set('event', 'contests', self.contestlist)
        cw.set('event', 'id', EVENT_ID)
        _log.debug('Saving event config %r', self.configfile)
        with metarace.savefile(self.configfile) as f:
            cw.write(f)

    def do_properties(self):
        """Run race properties dialog."""
        _CONFIG_SCHEMA['contests']['value'] = ' '.join(self.contestlist)
        _CONFIG_SCHEMA['otherstime']['value'] = self.otherstime
        res = uiutil.options_dlg(
            window=self.meet.window,
            title='Sprint Properties',
            sections={
                'sprnd': {
                    'title': 'Sprint',
                    'schema': _CONFIG_SCHEMA,
                    'object': None,
                }
            },
            action=True,
        )
        if res['action'] == 0:  # OK
            self.otherstime = res['sprnd']['otherstime'][2]
            if res['sprnd']['contests'][0]:
                self.contestlist = res['sprnd']['contests'][2].split()
                _log.debug('Contests altered, reload required')
                GLib.idle_add(self.meet.open_event,
                              self.event,
                              priority=GLib.PRIORITY_LOW)
        else:
            _log.debug('Edit propertied cancelled')
        return False

    def resettimer(self):
        """Reset race timer."""
        self.finish = None
        self.start = None
        self.lstart = None
        self.curelap = None
        self.timerstat = 'idle'
        self.meet.main_timer.dearm(self.startchan)
        self.meet.main_timer.dearm(0)
        self.meet.main_timer.dearm(self.finchan)
        self.stat_but.update('idle', 'Idle')
        self.stat_but.set_sensitive(True)
        self._status = None
        self._weather = None
        self._infoLine = None
        self.set_elapsed()

    def setrunning(self):
        """Set timer state to 'running'."""
        self.timerstat = 'running'
        self.stat_but.update('ok', 'Running')

    def setfinished(self):
        """Set timer state to 'finished'."""
        self.timerstat = 'finished'
        self.stat_but.update('idle', 'Finished')
        self.stat_but.set_sensitive(False)

    def armstart(self):
        """Toggle timer arm start state."""
        if self.timerstat == 'idle':
            self.timerstat = 'armstart'
            self.stat_but.update('activity', 'Arm Start')
            self.meet.main_timer.arm(self.startchan)
            self.meet.main_timer.arm(0)
        elif self.timerstat == 'armstart':
            self.timerstat = 'idle'
            self.time_lbl.set_text('')
            self.stat_but.update('idle', 'Idle')
            self.meet.main_timer.dearm(self.startchan)
            self.meet.main_timer.dearm(0)
        return False  # for use in delayed callback

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
        ## NOTE: display todo
        tp = '200m:'
        self.meet.scbwin = scbwin.scbtimer(self.meet.scb, self.event['pref'],
                                           self.event['info'], tp)
        self.timerwin = True
        self.meet.scbwin.reset()
        self.meet.gemini.reset_fields()
        if self.timerstat == 'finished':
            if self.start is not None and self.finish is not None:
                elap = self.finish - self.start
                self.meet.scbwin.settime(elap.timestr(2))
                self.meet.scbwin.setavg(elap.speedstr(200))  # fixed dist
                self.meet.gemini.set_time(elap.rawtime(2))
            self.meet.scbwin.update()
        self.meet.gemini.show_brt()

    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == Gdk.EventType.KEY_PRESS:
            key = Gdk.keyval_name(event.keyval) or 'None'
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                if key == key_abort:  # override ctrl+f5
                    self.resettimer()
                    return True
                elif key == key_walk_a:
                    self.set_winner('A', wplace='w/o', lplace='dns')
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_walk_b:
                    self.set_winner('B', wplace='w/o', lplace='dns')
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_rel_a:
                    self.set_winner('B', wplace='1.', lplace='rel')
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_rel_b:  # rel B => A wins
                    self.set_winner('A', wplace='1.', lplace='rel')
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_startlist:  # re-load starters
                    self.reload_riders()
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
                    self.redo_places()
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_win_a:
                    self.set_winner('A')
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_win_b:
                    self.set_winner('B')
                    GLib.idle_add(self.delayed_announce)
                    return True
        return False

    def set_winner(self, win, wplace='1.', lplace='2.'):
        i = self.current_contest_combo.get_active_iter()
        if i is not None:  # contest selected ok
            prevwin = self.contests.get_value(i, COL_WINNER)
            cid = self.contests.get_value(i, COL_CONTEST)
            if prevwin:  # warn override
                _log.info('Overwriting contest winner: %r', prevwin)
            wno = ''
            lno = ''
            fstr = None
            ft = self.contests.get_value(i, COL_200M)
            if ft is not None:
                fstr = ft.rawtime(2)
            if win == 'A':
                self.contests.set_value(i, COL_A_PLACE, wplace)
                self.contests.set_value(i, COL_B_PLACE, lplace)
                wno = self.contests.get_value(i, COL_A_NO)
                lno = self.contests.get_value(i, COL_B_NO)
                self.contests.set_value(i, COL_WINNER, wno)
            else:
                self.contests.set_value(i, COL_B_PLACE, wplace)
                self.contests.set_value(i, COL_A_PLACE, lplace)
                wno = self.contests.get_value(i, COL_B_NO)
                lno = self.contests.get_value(i, COL_A_NO)
                self.contests.set_value(i, COL_WINNER, wno)
            if not prevwin:
                self.do_places(cid, wno, wplace, lno, lplace, fstr)
                self.meet.gemini.set_bib(wno)
                if fstr is not None:
                    self.meet.gemini.set_time(fstr.strip().rjust(4) + ' ')
                self.meet.gemini.show_brt()
        self.standingstr()
        if self.winopen:
            self.meet.delayed_export()
            if self._weather is None:
                self._weather = self.meet.get_weather()

    def redo_places(self):
        i = self.current_contest_combo.get_active_iter()
        if i is not None:  # contest selected ok
            cid = self.contests.get_value(i, COL_CONTEST)
            win = self.contests.get_value(i, COL_WINNER)
            ano = self.contests.get_value(i, COL_A_NO)
            wno = ''
            wplace = ''
            lno = ''
            fstr = None
            ft = self.contests.get_value(i, COL_200M)
            if ft is not None:
                fstr = ft.rawtime(2)
            if win == ano:
                wplace = self.contests.get_value(i, COL_A_PLACE)
                lplace = self.contests.get_value(i, COL_B_PLACE)
                wno = self.contests.get_value(i, COL_A_NO)
                lno = self.contests.get_value(i, COL_B_NO)
            else:
                wplace = self.contests.get_value(i, COL_B_PLACE)
                lplace = self.contests.get_value(i, COL_A_PLACE)
                wno = self.contests.get_value(i, COL_B_NO)
                lno = self.contests.get_value(i, COL_A_NO)
            self.do_places(cid, wno, wplace, lno, lplace, fstr)
            self.meet.delayed_export()

    def do_places(self, contest, winno, winpl, loseno, losepl, ftime):
        """Show contest result on scoreboard."""
        self.meet.scbwin = None
        self.timerwin = False
        name_w = self.meet.scb.linelen - 12
        winname, winclub = self._getname(winno, width=name_w)
        if len(winclub) != 3:
            winclub = ''
        losename, loseclub = self._getname(loseno, width=name_w)
        if len(loseclub) != 3:
            loseclub = ''
        result = (('', '', '', ''), (winpl, winno, winname, winclub),
                  (losepl, loseno, losename, loseclub))
        fmt = ((3, 'l'), (3, 'r'), ' ', (name_w, 'l'), (5, 'r'))
        self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                           head=self.meet.racenamecat(
                                               self.event),
                                           subhead=contest,
                                           coldesc=fmt,
                                           rows=result,
                                           timepfx='200m:',
                                           timestr=ftime)
        self.meet.scbwin.reset()
        if self._weather is None:
            self._weather = self.meet.get_weather()

    def _getname(self, bib, width=32):
        """Return a name and club for the rider if known"""
        name = ''
        club = ''
        dbr = self.meet.rdb.get_rider(bib, self.series)
        if dbr is not None:
            name = dbr.fitname(width)
            club = dbr['organisation']
        return name, club

    def do_startlist(self):
        """Show start list on scoreboard."""
        # clear gem board
        self.meet.gemini.reset_fields()
        self.meet.gemini.show_brt()

        # prepare start list board	(use 2+2)
        cid = ''
        startlist = []
        i = self.current_contest_combo.get_active_iter()
        name_w = self.meet.scb.linelen - 10
        if i is not None:  # contest selected ok
            cid = self.contests.get_value(i, COL_CONTEST)
            asm = ''
            bsm = ''
            if self.event['type'] == 'sprint final':
                ckey = self.contestroot(cid)
                if self._rescache[ckey]['a']:
                    asm = '*'
                if self._rescache[ckey]['b']:
                    bsm = '*'
            # TODO: is there a case for "info"
            ano = self.contests.get_value(i, COL_A_NO)
            name, club = self._getname(ano, width=name_w)
            if len(club) != 3:
                club = ''
            startlist.append((asm, ano, name, club))
            bno = self.contests.get_value(i, COL_B_NO)
            name, club = self._getname(bno, width=name_w)
            if len(club) != 3:
                club = ''
            startlist.append((bsm, bno, name, club))
        self.meet.scbwin = None
        self.timerwin = False
        fmt = ((1, 'l'), (3, 'r'), ' ', (name_w, 'l'), (5, 'r'))
        self.meet.scbwin = scbwin.scbintsprint(
            self.meet.scb, self.meet.racenamecat(self.event), cid, fmt,
            startlist)
        self.meet.scbwin.reset()

    def update_expander_lbl_cb(self):
        """Update race info expander label."""
        self.info_expand.set_label(self.meet.infoline(self.event))

    def editent_cb(self, entry, col):
        """Shared event entry update callback."""
        if col == 'pref':
            self.event['pref'] = entry.get_text()
        elif col == 'info':
            self.event['info'] = entry.get_text()

    def starttrig(self, e, wallstart=None):
        """React to start trigger."""
        if self.timerstat == 'armstart':
            self.start = e
            if wallstart:
                self.lstart = wallstart
            else:
                self.lstart = tod.now()
            self.setrunning()
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
            cid = ''
            i = self.current_contest_combo.get_active_iter()
            if i is not None:  # contest selected ok
                cid = self.contests.get_value(i, COL_CONTEST)
                self.contests.set_value(i, COL_200M, self.curelap)
                self.ctrl_winner.grab_focus()
            self.log_elapsed(cid)
            if self.timerwin and type(self.meet.scbwin) is scbwin.scbtimer:
                self.showtimer()
                if self.start is not None:
                    self.meet.gemini.rtick(self.finish - self.start, 2)
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
                elapstr = self.time_lbl.get_text()
                self.meet.scbwin.settime(elapstr)
                self.meet.gemini.set_time(elapstr.strip().rjust(4) + ' ')
                self.meet.gemini.show_brt()
        return True

    def set_start(self, start='', lstart=None):
        """Set the race start."""
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
                self.setrunning()

    def log_elapsed(self, contest=''):
        """Log race elapsed time on Timy."""
        if contest:
            self.meet.main_timer.printline('Ev ' + self.evno + ' [' + contest +
                                           ']')
        self.meet.main_timer.printline('      ST: ' + self.start.timestr(4))
        self.meet.main_timer.printline('     FIN: ' + self.finish.timestr(4))
        self.meet.main_timer.printline('    TIME: ' +
                                       (self.finish - self.start).timestr(2))

    def set_finish(self, finish=''):
        """Set the race finish."""
        if type(finish) is tod.tod:
            self.finish = finish
        else:
            self.finish = tod.mktod(finish)
        if self.finish is None:
            if self.start is not None:
                self.setrunning()
        else:
            if self.start is None:
                self.set_start('0')
            self.setfinished()

    def set_elapsed(self):
        """Update elapsed time in race ui and announcer."""
        self.curelap = None
        if self.start is not None and self.finish is not None:
            et = self.finish - self.start
            self.time_lbl.set_text(et.timestr(2))
            self.curelap = et
        elif self.start is not None:  # Note: uses 'local start' for RT
            runtm = (tod.now() - self.lstart).timestr(1)
            self.time_lbl.set_text(runtm)
        elif self.timerstat == 'armstart':
            self.time_lbl.set_text(tod.tod(0).timestr(1))
        else:
            self.time_lbl.set_text('')

    def current_contest_combo_changed_cb(self, combo, data=None):
        """Copy elapsed time into timer (dodgey)."""
        self.resettimer()
        i = self.current_contest_combo.get_active_iter()
        if i is not None:  # contest selected ok
            ft = self.contests.get_value(i, COL_200M)
            if ft is not None:
                self.start = tod.tod(0)
                self.finish = ft
                self.set_elapsed()
            else:
                self.start = None
                self.finish = None
                self.set_elapsed()
            winner = self.contests.get_value(i, COL_WINNER)
            self.ctrl_winner.set_text(winner)

    def race_ctrl_winner_activate_cb(self, entry, data=None):
        """Manual entry of race winner."""
        winner = entry.get_text()
        i = self.current_contest_combo.get_active_iter()
        if i is not None:  # contest selected ok
            cid = self.contests.get_value(i, COL_CONTEST)
            self.ctrl_winner.grab_focus()
            ano = self.contests.get_value(i, COL_A_NO)
            bno = self.contests.get_value(i, COL_B_NO)
            if winner == ano:
                self.set_winner('A')
                GLib.idle_add(self.delayed_announce)
            elif winner == bno:
                self.set_winner('B')
                GLib.idle_add(self.delayed_announce)
            else:
                _log.error('Ignored rider not in contest')
            if self._weather is None:
                self._weather = self.meet.get_weather()
        else:
            _log.info('No contest selected')

    def race_info_time_edit_activate_cb(self, button):
        """Display contest timing edit dialog."""
        ostx = ''
        oftx = ''
        if self.start is not None:
            ostx = self.start.rawtime(4)
        else:
            ostx = '0.0'
        if self.finish is not None:
            oftx = self.finish.rawtime(4)
        ret = uiutil.edit_times_dlg(self.meet.window, ostx, oftx)
        if ret[0] == 1:
            try:
                stod = None
                if ret[1]:
                    stod = tod.tod(ret[1], 'MANU', 'C0i')
                    self.meet.main_timer.printline(' ' + str(stod))
                ftod = None
                if ret[2]:
                    ftod = tod.tod(ret[2], 'MANU', 'C1i')
                    self.meet.main_timer.printline(' ' + str(ftod))
                self.set_start(stod)
                self.set_finish(ftod)
                self.set_elapsed()
                cid = ''
                i = self.current_contest_combo.get_active_iter()
                if i is not None:  # contest selected ok
                    cid = self.contests.get_value(i, COL_CONTEST)
                    self.contests.set_value(i, COL_200M, self.curelap)
                if self.start is not None and self.finish is not None:
                    self.log_elapsed(cid)
                _log.info('Updated race times')
            except Exception as v:
                _log.error('%s updating times: %s', v.__class__.__name__, v)

            GLib.idle_add(self.delayed_announce)
        else:
            _log.info('Edit race times cancelled')

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        if self.winopen:
            self.meet.txt_clear()
            self.meet.txt_title(self.event.get_info(showevno=True))
            lapstring = strops.lapstring(self.event['laps'])
            substr = ' '.join((
                lapstring,
                self.event['distance'],
                self.event['rules'],
            )).strip()
            if substr:
                self.meet.txt_postxt(1, 0, substr.center(80))
            self.meet.txt_line(2, '_')
            self.meet.txt_line(8, '_')
            # announce current contest
            i = self.current_contest_combo.get_active_iter()
            if i is not None:  # contest selected ok
                cid = self.contests.get_value(i, COL_CONTEST)
                self.meet.txt_postxt(4, 0, 'Contest: ' + cid)
                ano = self.contests.get_value(i, COL_A_NO).rjust(3)
                astr = self.contests.get_value(i, COL_A_STR)
                aplace = self.contests.get_value(i, COL_A_PLACE).ljust(3)
                bni = self.contests.get_value(i, COL_B_NO)
                bno = bni.rjust(3)
                bstr = self.contests.get_value(i, COL_B_STR)
                bplace = self.contests.get_value(i, COL_B_PLACE).ljust(3)
                if self.contests.get_value(i, COL_WINNER) == bni:
                    self.meet.txt_postxt(6, 0, bplace + ' ' + bno + ' ' + bstr)
                    self.meet.txt_postxt(7, 0, aplace + ' ' + ano + ' ' + astr)
                else:
                    self.meet.txt_postxt(6, 0, aplace + ' ' + ano + ' ' + astr)
                    self.meet.txt_postxt(7, 0, bplace + ' ' + bno + ' ' + bstr)
                ft = self.contests.get_value(i, COL_200M)
                if ft is not None:
                    self.meet.txt_postxt(6, 60,
                                         '200m: ' + ft.rawtime(2).rjust(10))
                    self.meet.txt_postxt(
                        7, 60, ' Avg: ' + ft.speedstr().strip().rjust(10))
            # show 'leaderboard'
            lof = 10
            for c in self.contests:
                cid = (c[COL_CONTEST] + ':').ljust(8)
                win = c[COL_WINNER]
                lr = ''
                rr = ''
                sep = ' v '
                if win:
                    if c[COL_BYE]:
                        sep = '   '
                    else:
                        sep = 'def'
                if win == c[COL_B_NO]:
                    lr = (c[COL_B_NO].rjust(3) + ' ' +
                          strops.truncpad(c[COL_B_STR], 29))
                    rr = (c[COL_A_NO].rjust(3) + ' ' +
                          strops.truncpad(c[COL_A_STR], 29))
                else:
                    lr = (c[COL_A_NO].rjust(3) + ' ' +
                          strops.truncpad(c[COL_A_STR], 29))
                    rr = (c[COL_B_NO].rjust(3) + ' ' +
                          strops.truncpad(c[COL_B_STR], 29))
                self.meet.txt_postxt(lof, 0, ' '.join([cid, lr, sep, rr]))
                lof += 1
            self.resend_current()
        return False

    def result_gen(self):
        """Generator function to export a final result."""
        # Note: "Others" are placed according to qualifying time,
        #       (ref UCI 3.2.050) with a fall back to incoming rank
        others = []
        placeoft = 1
        if self.event['type'] == 'sprint final':
            for cid in self._rescache:
                win = None
                lose = None
                rank = None
                wtime = None
                ltime = None
                cm = self._rescache[cid]
                info = None
                lr = False
                if cm['a'] > 1:
                    win = cm['ano']
                    wtime = cm['aqual']
                    lose = cm['bno']
                    ltime = cm['bqual']
                elif cm['b'] > 1:
                    win = cm['bno']
                    wtime = cm['bqual']
                    lose = cm['ano']
                    ltime = cm['aqual']
                if win is not None:
                    rank = placeoft
                    lr = True  # include rank on loser rider
                if not cm['bye']:
                    if ltime is None or not self.otherstime:
                        ltime = tod.MAX
                    others.append((ltime, -placeoft, lose, lr))
                    #cstack.insert(0, (lose, lr, ltime))
                time = None
                yield (win, rank, wtime, info)
                placeoft += 1
        else:
            for c in self.contests:
                rank = None
                wtime = None
                ltime = None
                info = None
                win = c[COL_A_NO]
                lose = c[COL_B_NO]
                lr = False
                if c[COL_WINNER]:
                    rank = placeoft
                    win = c[COL_WINNER]
                    if lose == win:  # win went to 'B' rider
                        lose = c[COL_A_NO]
                        wtime = c[COL_B_QUAL]
                        ltime = c[COL_A_QUAL]
                    else:
                        wtime = c[COL_A_QUAL]
                        ltime = c[COL_B_QUAL]
                    lr = True  # include rank on loser rider
                ltime = tod.MAX if ltime is None else ltime
                others.append((ltime, -placeoft, lose, lr))
                time = None
                yield (win, rank, wtime, info)
                placeoft += 1

        others.sort()
        for (time, junk, bib, lr) in others:
            rank = None
            info = None  # rel/dsq/etc?
            if time == tod.MAX:
                time = None
            if lr:
                rank = placeoft
            yield (bib, rank, time, info)
            placeoft += 1

    def update_reslines(self):
        """Pull in final result using result_gen"""
        self._reslines = []
        count = 0
        for res in self.result_gen():
            count += 1
            if res[0] and res[1] and res[0].strip():
                rno = res[0]
                rname = ''
                rnat = ''
                rcls = ''
                rh = self.meet.rdb.get_rider(rno, self.series)
                if rh is not None:
                    rno = rh['no']
                    rname = rh.resname()
                    rnat = rh['nation']
                    rcls = rh['class']
                rank = count
                place = str(res[1])
                if place.isdigit():
                    place += '.'
                self._reslines.append({
                    'rank': rank,
                    'class': place,
                    'competitor': rno,
                    'nation': rnat,
                    'name': rname,
                    'info': rcls,
                })

    def _fill_competitor(self, obj):
        """Fill in the db infor for a competitor line/result line"""
        # todo: move to rdb or data bridge and re-use
        if 'competitor' in obj and obj['competitor']:
            rno = obj['competitor']
            rh = self.meet.rdb.get_rider(rno)
            if rh is not None:
                obj['nation'] = rh['nation']
                obj['name'] = rh.resname()
                obj['info'] = rh['class']
                pname = None
                ph = self.meet.rdb.get_pilot(rh)
                if ph is not None:
                    pname = ph.resname()
                obj['pilot'] = pname
                # todo: members

    def result_report(self, recurse=False):
        """Return a list of report sections containing the race result."""
        ret = []
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        if self.event['type'] == 'sprint final':
            sec = report.sprintfinal(secid)
        else:
            sec = report.sprintround(secid)
        sec.nobreak = True
        sec.heading = self.event.get_info(showevno=True)
        sec.lines = []
        lapstring = strops.lapstring(self.event['laps'])
        substr = '\u3000'.join(
            (lapstring, self.event['distance'], self.event['rules'])).strip()
        shvec = []
        if substr:
            shvec.append(substr)
        stand = self.standingstr()
        if stand:
            shvec.append(stand)
        if shvec:
            sec.subheading = '\u3000'.join(shvec)

        if self.event['type'] == 'sprint final':
            for cid in self._rescache:
                cm = self._rescache[cid]
                aname = self._resname(cm['ano'])
                bname = self._resname(cm['bno'])
                if cm['bye']:
                    sec.lines.append([
                        cid + ':',
                        [
                            None, cm['ano'], aname, cm['aqual'], None, None,
                            None, None
                        ],
                        [None, ' ', ' ', None, None, None, None, None],
                    ])
                else:
                    sec.lines.append([
                        cid + ':',
                        [
                            None, cm['ano'], aname, cm['aqual'],
                            cm['ares']['1'], cm['ares']['2'], cm['ares']['3'],
                            None
                        ],
                        [
                            None, cm['bno'], bname, cm['bqual'],
                            cm['bres']['1'], cm['bres']['2'], cm['bres']['3'],
                            None
                        ],
                    ])
        else:
            for cr in self.contests:
                # if winner set, report a result
                # otherwise, use startlist style:
                aqual = None
                if cr[COL_A_QUAL] is not None:
                    aqual = cr[COL_A_QUAL].rawtime(2)
                bqual = None
                if cr[COL_B_QUAL] is not None:
                    bqual = cr[COL_B_QUAL].rawtime(2)
                aname = self._resname(cr[COL_A_NO])
                bname = self._resname(cr[COL_B_NO])
                cprompt = cr[COL_CONTEST] + ':'
                if cr[COL_WINNER]:
                    avec = [cr[COL_A_PLACE], cr[COL_A_NO], aname, aqual]
                    bvec = [cr[COL_B_PLACE], cr[COL_B_NO], bname, bqual]
                    ft = None
                    if cr[COL_200M] is not None:
                        ft = cr[COL_200M].rawtime(2)
                    else:
                        ft = ' '
                    if cr[COL_WINNER] == cr[COL_A_NO]:
                        sec.lines.append([cprompt, avec, bvec, ft])
                    else:
                        sec.lines.append([cprompt, bvec, avec, ft])
                else:
                    sec.lines.append([
                        cprompt, [None, cr[COL_A_NO], aname, aqual],
                        [None, cr[COL_B_NO], bname, bqual], None
                    ])

        ret.append(sec)

        if len(self.decisions) > 0:
            ret.append(self.meet.decision_section(self.decisions))

        # for sprnd/final use result_gen to rearrange result report
        self.update_reslines()

        return ret

    def todstr(self, col, cr, model, iter, data=None):
        """Format tod into text for listview."""
        ft = model.get_value(iter, COL_200M)
        if ft is not None:
            cr.set_property('text', ft.rawtime(2))
        else:
            cr.set_property('text', '')

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

        self.readonly = not ui
        rstr = ''
        if self.readonly:
            rstr = 'readonly '
        _log.debug('Init %sevent %s', rstr, self.evno)
        self.winopen = ui

        self.onestart = False
        self.start = None
        self.lstart = None
        self.finish = None
        self.curelap = None
        self.timerwin = False
        self.timerstat = 'idle'
        self.inomnium = False
        self.startchan = 4
        self.finchan = 1
        self.otherstime = True  # Order places of "others" by qualifying time
        self.contestlist = []  # Configured list of contest labels
        self.contests = None
        self.decisions = []
        self._standingstat = ''
        self._rescache = {}
        self.finished = False
        self._winState = {}  # cache ui settings for headless load/save
        self._status = None
        self._weather = None
        self._startlines = None
        self._conteststarts = None
        self._reslines = None
        self._infoLine = None
        self._cursprint = None
        self._sprintres = None

        self.contests = Gtk.ListStore(
            str,  # COL_CONTEST = 0
            str,  # COL_A_NO = 1
            str,  # COL_A_STR = 2
            str,  # COL_A_PLACE = 3
            str,  # COL_B_NO = 4
            str,  # COL_B_STR = 5
            str,  # COL_B_PLACE = 6
            object,  # COL_200M = 7
            str,  # COL_WINNER = 8
            str,  # COL_COMMENT = 9
            object,  # COL_A_QUAL = 10
            object,  # COL_B_QUAL = 11
            bool,  # COL_BYE = 12
        )

        # start timer and show window
        if ui:
            b = uiutil.builder('sprnd.ui')
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
            self.type_lbl = b.get_object('race_type')
            self.type_lbl.set_text(self.event['type'].capitalize())

            # ctrl pane
            self.stat_but = uiutil.statButton()
            self.stat_but.set_sensitive(True)
            b.get_object('race_ctrl_stat_but').add(self.stat_but)

            self.ctrl_winner = b.get_object('race_ctrl_winner')
            self.ctrl_action_combo = b.get_object('race_ctrl_action_combo')
            self.ctrl_action = b.get_object('race_ctrl_action')
            self.action_model = b.get_object('race_action_model')

            self.current_contest_combo = b.get_object('current_contest_combo')
            self.current_contest_combo.set_model(self.contests)
            self.current_contest_combo.connect(
                'changed', self.current_contest_combo_changed_cb)

            # riders pane
            t = Gtk.TreeView(self.contests)
            self.view = t
            t.set_reorderable(False)
            t.set_enable_search(False)
            t.set_rules_hint(True)

            # riders columns
            uiutil.mkviewcoltxt(t, 'Contest', COL_CONTEST)
            uiutil.mkviewcoltxt(t, '', COL_A_NO, calign=1.0)
            uiutil.mkviewcoltxt(t, 'A Rider', COL_A_STR, expand=True)
            uiutil.mkviewcoltxt(t, '', COL_B_NO, calign=1.0)
            uiutil.mkviewcoltxt(t, 'B Rider', COL_B_STR, expand=True)
            uiutil.mkviewcoltod(t, '200m', cb=self.todstr)
            uiutil.mkviewcoltxt(t, 'Win', COL_WINNER)
            t.show()
            b.get_object('race_result_win').add(t)
            b.connect_signals(self)
