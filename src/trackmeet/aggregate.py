# SPDX-License-Identifier: MIT
"""Aggregate meta-event handler for trackmeet."""

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
from metarace import jsonconfig
from metarace import tod
from metarace import strops
from metarace import report

from . import uiutil
from . import scbwin
from . import classification

_log = logging.getLogger('blagg')
_log.setLevel(logging.DEBUG)

# config version string
EVENT_ID = 'blagg-2.1'

# Model columns
COL_NO = 0
COL_NAME = 1
COL_CAT = 4
COL_PLACE = 5
COL_MEDAL = 6
COL_TALLY = 6  # Store displayed points tally in medal col

# scb function key mappings
key_reannounce = 'F4'  # (+CTRL)
key_abort = 'F5'  # (+CTRL)
key_startlist = 'F3'
key_results = 'F4'

_CONFIG_SCHEMA = {
    'etype': {
        'prompt': 'Aggregate Properties',
        'control': 'section',
    },
    'afinal': {
        'prompt': 'A Finals:',
        'hint': 'List of events considered A finals',
        'default': '',
        'attr': 'afinal',
    },
    'afinalpts': {
        'prompt': 'A Final Pts:',
        'hint': 'List of points awarded for A finals',
        'default': '40 32 26 22 18 14 12 10 8 6 4 2 +',
        'attr': 'afinalpts',
    },
    'bfinal': {
        'prompt': 'B Finals:',
        'hint': 'List of events considered B finals',
        'default': '',
        'attr': 'bfinal',
    },
    'bfinalpts': {
        'prompt': 'B Final Pts:',
        'hint': 'List of points awarded for B finals',
        'default': '20 16 13 11 9 7 6 5 4 3 2 1 +',
        'attr': 'bfinalpts',
    },
    'aheat': {
        'prompt': 'A Heats:',
        'hint': 'List of events considered A heats',
        'default': '',
        'attr': 'aheat',
    },
    'aheatpts': {
        'prompt': 'A Heat Pts:',
        'hint': 'List of points awarded for A heats',
        'default': '20 16 13 11 9 7 6 4 2 +',
        'attr': 'aheatpts',
    },
    'bheat': {
        'prompt': 'B Heats:',
        'hint': 'List of events considered B heats',
        'default': '',
        'attr': 'bheat',
    },
    'bheatpts': {
        'prompt': 'B Heat Pts:',
        'hint': 'List of points awarded for B heats',
        'default': '10 8 7 6 5 4 3 2 1 +',
        'attr': 'bheatpts',
    },
    'bestindiv': {
        'prompt': 'Best Indiv:',
        'control': 'short',
        'type': 'int',
        'attr': 'bestindiv',
        'hint':
        'Max individual places from each team that count toward aggregate',
        'subtext': '(places)',
        'default': 2,
    },
    'bestteam': {
        'prompt': 'Best Teams:',
        'control': 'short',
        'type': 'int',
        'attr': 'bestteam',
        'hint': 'Max team places from that count toward aggregate',
        'subtext': '(places)',
        'default': 1,
    },
    'prelabel': {
        'prompt': 'Prev Meet:',
        'attr': 'prelabel',
        'default': None,
        'hint': 'Label for standings at start of meet',
    },
}


class teamagg(classification.classification):
    """Crude Teams Aggregate - based on organisation field"""

    def loadconfig(self):
        """Load race config from disk."""
        _log.debug('teamagg: loadconfig')
        findsource = False

        cr = jsonconfig.config({
            'event': {
                'id': EVENT_ID,
                'showinfo': False,
                'showcats': False,
                'showevents': '',
                'decisions': [],
                'placesrc': '',
                'medals': '',
            }
        })
        cr.add_section('event', _CONFIG_SCHEMA)
        if not cr.load(self.configfile):
            _log.info('%r not read, loading defaults', self.configfile)
        cr.export_section('event', self)

        self.showcats = cr.get_bool('event', 'showcats')
        self.decisions = cr.get('event', 'decisions')

        if self.winopen:
            self.update_expander_lbl_cb()
            self.info_expand.set_expanded(
                strops.confopt_bool(cr.get('event', 'showinfo')))
        else:
            self._winState['showinfo'] = cr.get('event', 'showinfo')

        self.recalculate()  # model is cleared and loaded in recalc

        eid = cr.get('event', 'id')
        if eid and eid != EVENT_ID:
            _log.info('Event config mismatch: %r != %r', eid, EVENT_ID)

    def saveconfig(self):
        """Save race to disk."""
        _log.debug('teamagg: saveconfig')
        if self.readonly:
            _log.error('Attempt to save readonly event')
            return
        cw = jsonconfig.config()
        cw.add_section('event', _CONFIG_SCHEMA)
        cw.import_section('event', self)
        cw.set('event', 'decisions', self.decisions)
        if self.winopen:
            cw.set('event', 'showinfo', self.info_expand.get_expanded())
        else:
            cw.set('event', 'showinfo', self._winState['showinfo'])
        cw.set('event', 'showcats', self.showcats)
        cw.set('event', 'id', EVENT_ID)
        _log.debug('Saving event config %r', self.configfile)
        with metarace.savefile(self.configfile) as f:
            cw.write(f)

    def result_report(self, recurse=True):  # by default include inners
        """Return a list of report sections containing the race result."""
        _log.debug('teamagg: result_report, recurse=%r', recurse)
        ret = []

        # start with the overall result
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)
        sec.units = 'pt'
        sec.nobreak = True  # TODO: check in comp
        sec.heading = self.event.get_info(showevno=True)
        lapstring = strops.lapstring(self.event['laps'])
        subvec = []
        substr = ' '.join(
            (lapstring, self.event['distance'], self.event['phase'])).strip()
        if substr:
            subvec.append(substr)
        stat = self.standingstr()
        if stat:
            subvec.append(stat)
        if subvec:
            sec.subheading = ' - '.join(subvec)

        teamnames = self.series.startswith('t')
        sec.lines = []
        for r in self.riders:
            rno = r[COL_NO]
            if teamnames:
                rno = ''
            rname = r[COL_NAME]
            rcls = ''
            plink = ''
            rh = self.meet.rdb.get_rider(r[COL_NO], self.series)
            # check for info override via rdb
            if rh is not None:
                rname = rh.resname()
                rcls = rh['class']
                if not rcls and self.showcats:
                    rcls = rh.primary_cat()
            rank = ''
            rks = r[COL_PLACE]
            if rks:
                rank = rks
                if rank.isdigit():
                    rank += '.'
            pts = r[COL_MEDAL]
            nrow = [rank, rno, rname, rcls, None, pts, plink]
            sec.lines.append(nrow)
        ret.append(sec)

        if self.ptstally:
            first = 'Points Detail'
            for cr in self.riders:
                cno = cr[COL_NO]
                if cno in self.ptstally:
                    # enforce truncation of final tally
                    total = int(self.ptstally[cno]['total'])
                    details = self.ptstally[cno]['detail']
                    composite = False
                    secid = 'detail-' + cno
                    sec = report.section(secid)
                    sec.units = 'pt'
                    #sec.nobreak = True  # TODO: check in comp
                    sec.heading = first
                    first = ''
                    sec.subheading = '%s %s' % (cr[COL_NAME],
                                                strops.rank2ord(cr[COL_PLACE]))
                    # extract an ordered list of events from detail
                    aux = []
                    cnt = 9999
                    for detail in details:
                        cnt += 1
                        evname = ''
                        evid = detail['evno']
                        evno = evid
                        evkey = cnt  # primary sorting key
                        evseries = ''
                        if evid in self.meet.edb:
                            evh = self.meet.edb[evid]
                            evno = evh['evov'] if evh['evov'] else evid
                            evkey = strops.confopt_posint(evno, cnt)
                            evname = self.meet.racenamecat(evh,
                                                           slen=28,
                                                           halign='l').strip()
                            evseries = evh['series']
                        aux.append(
                            (evkey, cnt, evno, evname, evseries, detail))
                    aux.sort()
                    for l in aux:
                        evno = l[2]
                        evname = l[3]
                        evseries = l[4]
                        detail = l[5]
                        rno = detail['rno']
                        rseries = detail['series']
                        rname = ''
                        dbr = self.meet.rdb.get_rider(rno, rseries)
                        if dbr is not None:
                            rname = dbr.fitname(3)
                        if dbr['series'] != evseries:
                            rname += ' *'
                            composite = True
                            _log.debug('Composite team rider in result')
                        sec.lines.append((
                            '',
                            '',
                            ': '.join((evname, rname)),
                            detail['type'],
                            strops.rank2ord(str(detail['place'])),
                            '%.3g' %
                            (detail['points'], ),  # but display fractions
                        ))
                    sec.lines.append(('', '', '', 'Total:', '', str(total)))
                    if composite:
                        sec.footer = '* denotes rider in composite team'
                    ret.append(sec)

        if len(self.decisions) > 0:
            ret.append(self.meet.decision_section(self.decisions))

        if recurse:  # for now leave in-place unless required
            # then append each of the specified events
            for evno in self.showevents.split():
                if evno:
                    _log.debug('Including results from event %r', evno)
                    r = self.meet.get_event(evno, False)
                    if r is None:
                        _log.error('Invalid event %r in showplaces', evno)
                        continue
                    r.loadconfig()  # now have queryable event handle
                    if r.onestart:  # go for result
                        ret.extend(r.result_report())
                    else:  # go for startlist
                        ret.extend(r.startlist_report())
                    r = None
        return ret

    def load_startpts(self):
        """Read initial points tally from CSV."""
        _log.debug('teamgg: read start points')
        pass

    def load_pointsmap(self, pstr, label):
        """Split points definition string into a place map"""
        pmap = {
            'label': label,
            'default': 0,
        }
        cnt = 0
        lp = 0
        for pt in pstr.split():
            cnt += 1
            if pt == '+':
                pmap['default'] = lp
                break  # degenerate points + n n
            else:
                pval = strops.confopt_posint(pt)
                if pval is not None:
                    pmap[cnt] = pval
                else:
                    _log.warning('Invalid points %r in %s', pt, label)
        return pmap

    def teamkey(self, teamname):
        """Return a comparison key for a team name"""
        return teamname.translate(strops.RIDERNO_UTRANS).upper()

    def lookup_competitor(self, no, series, pts):
        """Determine destinations for given competitor"""
        ret = {}

        dbr = self.meet.rdb.get_rider(no, series)
        if dbr is not None:
            team = dbr['organisation']
            if not team and series.startswith('t'):
                team = dbr['first']  # Assume team name only
            cno = self.teamkey(team)
            if cno == 'COMPOSITE':
                # riders not all same team
                members = dbr['members'].split()
                splitpts = pts / len(members)
                _log.debug('Composite team %s with %d members: %r @ %.2f pt',
                           no, len(members), members, splitpts)
                for member in members:
                    trh = self.meet.rdb.fetch_bibstr(member)
                    if trh is not None:
                        trteam = trh['organisation']
                        trrno = trh['no']
                        trseries = trh['series']
                        trcno = self.teamkey(trteam)
                        if trcno not in self.ptstally:
                            self.ptstally[trcno] = {
                                'name': trteam,
                                'total': 0,
                                'detail': [],
                            }
                        if trcno not in ret:
                            ret[trcno] = []
                        ret[trcno].append((trrno, trseries, splitpts))
                    else:
                        _log.debug('Missing rider %s in team %s', member, no)
            else:
                if cno not in self.ptstally:
                    self.ptstally[cno] = {
                        'name': team,
                        'total': 0,
                        'detail': [],
                    }
                # single rider/all in same team: return original detail
                ret[cno] = ((no, series, pts), )
        else:
            _log.warning('Unknown competitor %s skipped', no, series)
        _log.debug('lookup competitor returns: %r', ret)
        return ret

    def accumulate_event(self, evno, pmap):
        if evno == self.evno:
            _log.warning('Event %r: Self-reference ignored', evno)
            return
        r = self.meet.get_event(evno, False)
        if r is None:
            _log.warning('Event %r not found for lookup %r', evno,
                         pmap['label'])
            return
        r.loadconfig()  # now have queryable event handle
        bestn = self.bestindiv
        if r.series.startswith('t'):
            bestn = self.bestteam
        _log.debug('Accumulating best %d places from %s', bestn, evno)
        teamcounts = {}
        if r.finished:
            for res in r.result_gen():
                if isinstance(res[1], int):
                    pval = pmap['default']
                    if res[1] in pmap:
                        pval = pmap[res[1]]
                    if pval > 0:
                        # who do these points go to?
                        cpmap = self.lookup_competitor(res[0], r.series, pval)
                        for cno, rlist in cpmap.items():
                            if cno not in teamcounts:  # for this event
                                teamcounts[cno] = 0
                            if teamcounts[cno] < bestn:
                                teamcounts[cno] += 1
                                for rline in rlist:
                                    # (rno, rseries, rpts)
                                    self.ptstally[cno]['total'] += rline[2]
                                    self.ptstally[cno]['detail'].append({
                                        'evno':
                                        evno,
                                        'rno':
                                        rline[0],
                                        'series':
                                        rline[1],
                                        'place':
                                        res[1],
                                        'points':
                                        rline[2],
                                        'type':
                                        pmap['label'],
                                    })
        else:
            _log.debug('Event %r skipped: not yet finished', evno)
            self.finished = False
        r = None
        return

    def recalculate(self):
        """Update internal model."""
        _log.debug('agg: recalculate')
        # all riders are re-loaded on recalc
        self.riders.clear()
        self.ptstally = {}
        self.finished = True  # cleared below

        # load pre-meet points tally (starting points)
        self.load_startpts()

        pmap = self.load_pointsmap(self.bheatpts, 'B Heat')
        for evno in self.bheat.split():
            self.accumulate_event(evno, pmap)
        pmap = self.load_pointsmap(self.aheatpts, 'A Heat')
        for evno in self.aheat.split():
            self.accumulate_event(evno, pmap)
        pmap = self.load_pointsmap(self.bfinalpts, 'B Final')
        for evno in self.bfinal.split():
            self.accumulate_event(evno, pmap)
        pmap = self.load_pointsmap(self.afinalpts, 'A Final')
        for evno in self.afinal.split():
            self.accumulate_event(evno, pmap)

        aux = []
        cnt = 0
        for cno, detail in self.ptstally.items():
            cnt += 1
            total = int(detail['total'])
            aux.append((-total, cno, cnt, total, detail))
        if aux:
            aux.sort()
            lv = None
            cnt = 0
            plc = None
            for r in aux:
                cnt += 1
                detail = r[4]
                total = r[3]
                if total != lv:
                    plc = cnt
                lv = total
                nr = (r[1], detail['name'], '', '', '', str(plc), str(total))
                self.riders.append(nr)

        if len(self.riders) > 0:  # got at least one result to report
            self.onestart = True

        if self.finished:
            self._standingstat = 'Provisional Result'
        else:
            self._standingstat = 'Standings'

        return

    def do_places(self):
        """Show race result on scoreboard."""
        _log.debug('agg: do_places')
        # Draw a 'medal ceremony' on the screen
        resvec = []
        count = 0
        teamnames = False
        name_w = self.meet.scb.linelen - 13
        fmt = ((3, 'l'), (3, 'r'), ' ', (name_w, 'l'), (6, 'r'))
        if self.series.startswith('t'):
            teamnames = True
            name_w = self.meet.scb.linelen - 10
            fmt = ((3, 'l'), ' ', (name_w, 'l'), (6, 'r'))

        for r in self.riders:
            plstr = r[COL_PLACE]
            if plstr.isdigit():
                plstr = plstr + '.'
            ptstr = r[COL_TALLY]
            no = r[COL_NO]
            name = r[COL_NAME]
            if not teamnames:
                resvec.append((plstr, no, name, ptstr))
            else:
                resvec.append((plstr, name, ptstr))
            count += 1
        self.meet.scbwin = None
        header = self.meet.racenamecat(self.event)
        evtstatus = self._standingstat.upper()
        self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                           head=self.meet.racenamecat(
                                               self.event),
                                           subhead=evtstatus,
                                           coldesc=fmt,
                                           rows=resvec)
        self.meet.scbwin.reset()
        return False

    def do_properties(self):
        """Run race properties dialog."""
        res = uiutil.options_dlg(window=self.meet.window,
                                 action=True,
                                 title='Aggregate Properties',
                                 sections={
                                     'event': {
                                         'title': 'Aggregate',
                                         'schema': _CONFIG_SCHEMA,
                                         'object': self,
                                     },
                                 })
        if res['action'] == 0:  # OK
            _log.debug('Edit event properties confirmed')
            self.recalculate()
            GLib.idle_add(self.delayed_announce)
        else:
            _log.debug('Edit event properties cancelled')

        # if prefix is empty, grab input focus
        if not self.prefix_ent.get_text():
            self.prefix_ent.grab_focus()

    def __init__(self, meet, event, ui=True):
        """Constructor."""
        _log.debug('teamagg: __init__, meet=%r, event=%r, ui=%r', meet, event,
                   ui)
        self.meet = meet
        self.event = event  # Note: now a treerowref
        self.evno = event['evid']
        self.evtype = event['type']
        self.series = event['seri']
        self.configfile = meet.event_configfile(self.evno)

        # race run time attributes
        self.onestart = True  # always true for autospec classification
        self.showcats = False  # show primary category on result
        self.readonly = not ui
        rstr = ''
        if self.readonly:
            rstr = 'readonly '
        _log.debug('Init %sevent %s', rstr, self.evno)
        self.winopen = ui
        self.placesrc = ''  # leave unused
        self.medals = ''  # leave unused
        self.showevents = ''  # maybe re-used
        self.decisions = []
        self.finished = False
        self._standingstat = ''
        # aggregate properties
        self.afinal = ''
        self.afinalpts = ''
        self.bfinal = ''
        self.bfinalpts = ''
        self.aheat = ''
        self.aheatpts = ''
        self.bheat = ''
        self.bheatpts = ''
        self.bestindiv = 2
        self.bestteam = 1
        self.prelabel = None
        self.ptstally = {}  # cached content for the "detail" report
        self._winState = {}  # cache ui settings for headless load/save

        self.riders = Gtk.ListStore(
            str,  # 0 bib
            str,  # 1 name
            str,  # 2 reserved
            str,  # 3 reserved
            str,  # 4 comment
            str,  # 5 place
            str)  # 6 medal

        if ui:
            b = uiutil.builder('classification.ui')
            self.frame = b.get_object('classification_vbox')

            # info pane
            self.info_expand = b.get_object('info_expand')
            b.get_object('classification_info_evno').set_text(self.evno)
            self.showev = b.get_object('classification_info_evno_show')
            self.prefix_ent = b.get_object('classification_info_prefix')
            self.prefix_ent.set_text(self.event['pref'])
            self.prefix_ent.connect('changed', self.editent_cb, 'pref')
            self.info_ent = b.get_object('classification_info_title')
            self.info_ent.set_text(self.event['info'])
            self.info_ent.connect('changed', self.editent_cb, 'info')

            # riders pane
            t = Gtk.TreeView(self.riders)
            self.view = t
            t.set_rules_hint(True)

            # riders columns
            uiutil.mkviewcoltxt(t, 'No.', COL_NO, calign=1.0)
            uiutil.mkviewcoltxt(t,
                                'Name',
                                COL_NAME,
                                self._editname_cb,
                                expand=True)
            uiutil.mkviewcoltxt(t, 'Rank', COL_PLACE, halign=0.5, calign=0.5)
            uiutil.mkviewcoltxt(t, 'Pts', COL_MEDAL)
            t.show()
            b.get_object('classification_result_win').add(t)
            b.connect_signals(self)


class indivagg(teamagg):
    """Individual Aggregate"""

    def lookup_competitor(self, no, series, pts):
        """Individual is a degenerate team"""
        cno = strops.bibser2bibstr(no, series)
        if cno not in self.ptstally:
            cname = ''
            dbr = self.meet.rdb.get_rider(no, series)
            if dbr is not None:
                cname = dbr.listname()
            self.ptstally[cno] = {
                'name': cname,
                'total': 0,
                'detail': [],
            }
        return {cno: ((no, series, pts), )}

    def do_places(self):
        """Show race result on scoreboard."""
        _log.debug('indiv agg: do_places')
        resvec = []
        count = 0
        allteamnames = False
        name_w = self.meet.scb.linelen - 13
        fmt = ((3, 'l'), (3, 'r'), ' ', (name_w, 'l'), (6, 'r'))
        if self.series.startswith('t'):
            allteamnames = True
            name_w = self.meet.scb.linelen - 10
            fmt = ((3, 'l'), ' ', (name_w, 'l'), (6, 'r'))

        for r in self.riders:
            rno = r[COL_NO]
            rh = None
            rhid = self.meet.rdb.get_id(r[COL_NO])  # rno includes series
            if rhid is not None:
                rh = self.meet.rdb[rhid]
            rname = ''
            plink = ''
            tlink = []
            if rh is not None:
                rname = rh.fitname(name_w)
                teamnames = rh['series'].startswith('t')
                if teamnames:
                    rno = ''
                else:
                    # replace BIB.series with db riderno
                    rno = rh['no']
            plstr = r[COL_PLACE]
            if plstr.isdigit():
                plstr = plstr + '.'
            ptstr = r[COL_TALLY]
            if not allteamnames:
                resvec.append((plstr, rno, rname, ptstr))
            else:
                resvec.append((plstr, rname, ptstr))
            count += 1
        self.meet.scbwin = None
        header = self.meet.racenamecat(self.event)
        evtstatus = self._standingstat.upper()
        self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                           head=self.meet.racenamecat(
                                               self.event),
                                           subhead=evtstatus,
                                           coldesc=fmt,
                                           rows=resvec)
        self.meet.scbwin.reset()
        return False

    def result_report(self, recurse=True):  # by default include inners
        """Return a list of report sections containing the race result."""
        _log.debug('indivagg: result_report, recurse=%r', recurse)
        ret = []

        # start with the overall result
        self.showcats = True  # override cats for indiv result
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)
        sec.units = 'pt'
        sec.nobreak = True  # TODO: check in comp
        if recurse:
            sec.heading = ' '.join([self.event['pref'],
                                    self.event['info']]).strip()
        else:
            if self.event['evov']:
                sec.heading = ' '.join(
                    [self.event['pref'], self.event['info']]).strip()
            else:
                sec.heading = 'Event ' + self.evno + ': ' + ' '.join(
                    [self.event['pref'], self.event['info']]).strip()
        sec.lines = []
        lapstring = strops.lapstring(self.event['laps'])
        subvec = []
        substr = ' '.join(
            (lapstring, self.event['distance'], self.event['phase'])).strip()
        if substr:
            subvec.append(substr)
        stat = self.standingstr()
        if stat:
            subvec.append(stat)
        if subvec:
            sec.subheading = ' - '.join(subvec)

        sec.lines = []
        for r in self.riders:
            rno = r[COL_NO]
            rh = None
            rhid = self.meet.rdb.get_id(r[COL_NO])  # rno includes series
            if rhid is not None:
                rh = self.meet.rdb[rhid]
            rname = ''
            plink = ''
            tlink = []
            rcls = ''
            if rh is not None:
                rname = rh.resname()
                rcls = rh['class']
                if not rcls and self.showcats:
                    rcat = rh.primary_cat()

                teamnames = rh['series'].startswith('t')
                if teamnames:
                    rno = ''
                    for trno in rh['members'].split():
                        trh = self.meet.rdb.fetch_bibstr(trno)
                        if trh is not None:
                            trname = trh.resname()
                            trinf = trh['class']
                            tlink.append(
                                [None, trno, trname, trinf, None, None, None])
                else:
                    # replace BIB.series with db riderno
                    rno = rh['no']

                # TODO: PARA Pilots
                #if rh['cat'] and 'tandem' in rh['cat'].lower():
                #ph = self.meet.rdb.get_rider(rh['note'], self.series)
                #if ph is not None:
                #plink = [
                #'', '',
                #ph.resname() + ' - Pilot', ph['uciid'], '', '', ''
                #]

            rank = ''
            rks = r[COL_PLACE]
            if rks:
                rank = rks
                if rank.isdigit():
                    rank += '.'

            pts = r[COL_MEDAL]

            sec.lines.append([rks, rno, rname, rcls, None, pts, plink])
            if tlink:
                sec.lines.extend(tlink)
        ret.append(sec)

        if len(self.decisions) > 0:
            ret.append(self.meet.decision_section(self.decisions))

        if recurse:  # for now leave in-place unless required
            # then append each of the specified events
            for evno in self.showevents.split():
                if evno:
                    _log.debug('Including results from event %r', evno)
                    r = self.meet.get_event(evno, False)
                    if r is None:
                        _log.error('Invalid event %r in showplaces', evno)
                        continue
                    r.loadconfig()  # now have queryable event handle
                    if r.onestart:  # go for result
                        ret.extend(r.result_report())
                    else:  # go for startlist
                        ret.extend(r.startlist_report())
                    r = None
        return ret
