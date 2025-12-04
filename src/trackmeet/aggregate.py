# SPDX-License-Identifier: MIT
"""Aggregate meta-event handler for trackmeet."""

import os
import gi
import logging
import json

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
    'showdetail': {
        'prompt': 'Details:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Include with result?',
        'hint': 'Include points distribution report with result',
        'attr': 'showdetail',
        'default': True,
    },
    'seriestally': {
        'prompt': 'Series:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Separate tally?',
        'hint': 'Provide a separate round and series tally with result',
        'attr': 'seriestally',
        'default': True,
    },
    'prelabel': {
        'prompt': 'Prev Meet:',
        'attr': 'prelabel',
        'default': None,
        'hint': 'Label for standings at start of meet',
    },
    'predata': {
        'prompt': 'Prev Data:',
        'attr': 'predata',
        'default': None,
        'hint': 'Data file for previous meet tallies',
    },
}


class teamagg(classification.classification):
    """Crude Teams Aggregate - based on organisation field"""

    def ridercb(self, rider):
        """Rider change notification"""
        if self.winopen:
            if rider is not None:
                rno = rider[0]
                series = rider[1]
                if series == self.series:
                    self._tkcache.clear()
                    self.recalculate()
            else:
                # riders db changed, handled by meet object
                pass

    def data_bridge(self):
        """Export round points as result and series as subfrag"""
        fragment = self.event.get_fragment()
        if fragment:
            data = self.data_pack()

            # add series points as sub-fragment
            if self.seriestally:
                sid = 'series'
                subtitle = 'Series Points'
                path = fragment.split('/')
                pathlen = len(path)
                subtype = None
                if pathlen == 2:  # competition
                    subtype = 'phases'
                elif pathlen == 3:  # phase
                    subtype = 'contests'
                elif pathlen == 4:  # contest
                    subtype = 'heats'
                data[subtype] = {}

                subdata = {
                    'units': 'pt',
                    'competitionType': 'bunch',
                    'subtitle': 'Series Points',
                    'info': None,
                    'lines': self._sreslines,
                }

                # duplicate weather startTime, and startlist from event
                for k in ('status', 'competitors', 'weather', 'startTime'):
                    if k in data:
                        subdata[k] = data[k]

                # publish inter to bridge
                subfrag = '/'.join((fragment, sid))
                self.meet.db.updateFragment(self.event, subfrag, subdata)

                # save record of subfrag to head object
                data[subtype][sid] = subtitle

            self.meet.db.updateFragment(self.event, fragment, data)

    def data_pack(self):
        """Pack standard values for a current object"""
        ret = {}
        ret['units'] = 'pt'
        ret['status'] = self._status
        if self._startlines is not None:
            ret['competitors'] = self._startlines
        if self._reslines is not None:
            ret['lines'] = self._reslines
        if self._detail is not None:
            ret['detail'] = self._detail
        if len(self.decisions) > 0:
            ret['decisions'] = self.meet.decision_list(self.decisions)
        return ret

    def loadconfig(self):
        """Load race config from disk."""
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
        if self._status == 'provisional':
            savefile = 'event_%s_tally.json' % (str(self.evno), )
            with metarace.savefile(savefile) as f:
                json.dump(self.ptstally, f)

    def result_report(self, recurse=True):  # by default include inners
        """Team aggregate result"""
        ret = []

        # start with the overall result
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)
        sec.units = 'pt'
        sec.nobreak = True  # TODO: check in comp
        sec.heading = self.event.get_info(showevno=True)
        lapstring = strops.lapstring(self.event['laps'])
        subvec = []
        substr = '\u3000'.join(
            (lapstring, self.event['distance'], self.event['rules'])).strip()
        if substr:
            subvec.append(substr)
        stat = self.standingstr()
        if stat:
            subvec.append(stat)
        if subvec:
            sec.subheading = '\u3000'.join(subvec)

        teamnames = self.series.startswith('t')
        self._reslines = []
        self._sreslines = []
        sec.lines = []
        tstore = {}
        pcount = 0
        for r in self.riders:
            pcount += 1
            rno = r[COL_NO]
            tsk = rno
            dbrno, junk = strops.bibstr2bibser(rno)
            if teamnames:
                rno = ''
            rname = r[COL_NAME]
            rnat = None
            rcls = ''
            plink = ''
            rh = self.meet.rdb.get_rider(r[COL_NO], self.series)
            # check for info override via rdb
            if rh is not None:
                dbrno = rh['no']
                rname = rh.resname()
                rnat = rh['nation']
                rcls = rh['class']
                if not rcls and self.showcats:
                    rcls = rh.primary_cat()
            rank = ''
            rks = r[COL_PLACE]
            if rks:
                rank = rks
                if rank.isdigit():
                    pcount = int(rank)
                    rank += '.'

            pts = r[COL_MEDAL]

            tstore[tsk] = {
                'rno': rno,
                'dbrno': dbrno,
                'rname': rname,
                'rnat': rnat,
                'rcls': rcls,
                'plink': plink,
            }

            if pts != '0':  # suppress empty lines
                sec.lines.append([rank, rno, rname, rcls, None, pts, plink])
                self._reslines.append({
                    'rank': pcount,
                    'class': rank,
                    'competitor': dbrno,
                    'nation': rnat,
                    'name': rname,
                    'info': rcls,
                    'result': pts,
                })

        ret.append(sec)
        # also show series standings if configured and available
        if self.seriestally and self._seriespts:
            secid = 'ev-' + str(self.evno).translate(
                strops.WEBFILE_UTRANS) + '-spts'

        # also show series standings if configured and available
        if self.seriestally and self._seriespts:
            secid = 'ev-' + str(self.evno).translate(
                strops.WEBFILE_UTRANS) + '-spts'
            sec = report.section(secid)
            sec.units = 'pt'
            sec.nobreak = True  # TODO: check in comp
            sec.heading = ' '.join((self.event['pref'], 'Series Points'))
            lapstring = strops.lapstring(self.event['laps'])
            subvec = []
            substr = ' '.join((lapstring, self.event['distance'],
                               self.event['rules'])).strip()
            if substr:
                subvec.append(substr)
            stat = self.standingstr()
            if stat:
                subvec.append(stat)
            if subvec:
                sec.subheading = ' - '.join(subvec)
            pcount = 0
            for r in self._seriespts:
                pcount += 1
                tsk = r[COL_NO]
                iob = tstore[tsk]
                rank = ''
                rks = r[COL_PLACE]
                if rks:
                    rank = rks
                    if rank.isdigit():
                        pcount = int(rank)
                        rank += '.'
                pts = r[COL_MEDAL]
                if pts != '0':
                    sec.lines.append([
                        rank, iob['rno'], iob['rname'], iob['rcls'], None, pts,
                        iob['plink']
                    ])
                    self._sreslines.append({
                        'rank': pcount,
                        'class': rank,
                        'competitor': iob['dbrno'],
                        'nation': iob['rnat'],
                        'name': iob['rname'],
                        'info': iob['rcls'],
                        'result': pts,
                    })
            ret.append(sec)

        if self.showdetail:
            ret.extend(self.detail_report())

        if len(self.decisions) > 0:
            ret.append(self.meet.decision_section(self.decisions))

        # ignore event recursion in agg
        return ret

    def detail_report(self):
        ret = []
        self._detail = None
        if self.ptstally:
            self._detail = {}
            first = 'Points Detail'
            for cr in self.riders:
                cno = cr[COL_NO]
                dbcno, junk = strops.bibstr2bibser(cno)
                if cno in self.ptstally:
                    prevpts = self.prevpts[cno]
                    self._detail[cno] = {}
                    cObj = self._detail[cno]
                    # enforce truncation of final tally
                    total = self.ptstally[cno]['total']
                    stotal = prevpts + total
                    cObj['tally'] = {
                        'label': 'Tally',
                        'points': total,
                    }
                    if self.seriestally:
                        cObj['total'] = {
                            'label': 'Series',
                            'points': stotal,
                        }

                    details = self.ptstally[cno]['detail']
                    composite = False
                    secid = 'detail-' + cno
                    sec = report.section(secid)
                    sec.units = 'pt'
                    sec.heading = first
                    first = ''
                    sec.subheading = cr[COL_NAME]

                    # extract an ordered list of events from detail
                    aux = []
                    cnt = 9999
                    for detail in details:
                        cnt += 1
                        evname = ''
                        evid = detail['evno']
                        evno = evid
                        if evid == 'prev':  # previous round total
                            evkey = 999999
                        else:
                            evkey = cnt  # order by appearence
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
                    dcnt = 1
                    for l in aux:
                        evno = l[2]
                        evname = l[3]
                        evseries = l[4]
                        detail = l[5]
                        rno = detail['rno']
                        rseries = detail['series']
                        rname = ''
                        if rno:
                            dbr = self.meet.rdb.get_rider(rno, rseries)
                            if dbr is not None:
                                rname = dbr.fitname(3)
                                if dbr['series'] != evseries:
                                    rname += ' *'
                                    composite = True
                                    _log.debug(
                                        'Composite team rider in result')
                        label = ''
                        if evname:
                            label = ': '.join((evname, rname))
                        rkstr = ''
                        if detail['place']:
                            rkstr = strops.rank2ord(str(detail['place']))
                        ptsval = '%g' % (detail['points'], )
                        sec.lines.append((
                            '',
                            '',
                            label,
                            detail['type'],
                            rkstr,
                            ptsval,  # but display fractions
                        ))
                        cObj[str(dcnt)] = {
                            'label': label,
                            'rank': detail['place'],
                            'elapsed': None,
                            'interval': None,
                            'points': detail['points'],
                        }
                        dcnt += 1
                    sec.lines.append(
                        ('', '', '', 'Tally:', '', '%g' % (total, )))
                    if self.seriestally:
                        sec.lines.append(
                            ('', '', '', 'Series:', '', '%g' % (stotal, )))
                    if composite:
                        sec.footer = '* denotes rider in composite team'
                    ret.append(sec)
        return ret

    def load_startpts(self):
        """Read initial points tally."""
        prelabel = 'Previous Meet:'
        if self.prelabel is not None:
            prelabel = self.prelabel
        if self.predata is not None:
            if os.path.exists(self.predata):  # in the current folder only
                pd = None
                try:
                    with open(self.predata) as f:
                        pd = json.load(f)
                    if pd is not None and isinstance(pd, dict):
                        for tk in pd:
                            detail = pd[tk]
                            # opportunistic name lookup
                            th = self.meet.rdb.get_rider(tk, self.series)
                            if th is not None:
                                detail['name'] = th.resname()
                            oldpts = None
                            if 'series' in detail:  # prefer series tally
                                oldpts = detail['series']
                            elif 'total' in detail:  # fall back to total if not provided
                                oldpts = detail['total']

                            if oldpts is not None:
                                oldname = detail['name']
                                _log.debug('Prevpts: %s %s = %g', tk, oldname,
                                           oldpts)
                                self.add_competitor(tk, oldname)
                                self.prevpts[tk] = oldpts
                                self.ptstally[tk]['detail'].append({
                                    'evno':
                                    'prev',
                                    'rno':
                                    None,
                                    'series':
                                    None,
                                    'place':
                                    None,
                                    'points':
                                    oldpts,
                                    'type':
                                    prelabel,
                                })
                except Exception as e:
                    _log.warning('%s loading previous meet points: %s',
                                 e.__class__.__name__, e)

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
        if teamname in self._tkcache:
            return self._tkcache[teamname]

        # search teams in riderdb for matching name
        for t in self.meet.rdb.fromseries(self.series):
            team = self.meet.rdb[t]
            if team['name'] == teamname:
                tk = team['code']
                break
        else:
            # otherwise return the uppercase filtered key
            tk = teamname.translate(strops.RIDERNO_UTRANS).upper()

        if tk:
            self._tkcache[teamname] = tk
        return tk

    def lookup_competitor(self, no, series, pts):
        """Determine destinations for given competitor"""
        ret = {}

        dbr = self.meet.rdb.get_rider(no, series)
        if dbr is not None:
            team = dbr['organisation']
            if not team and series.startswith('t'):
                team = dbr['first']  # Assume team name only
                # should check each team member, and
                # overwrite composite/team if there's a deviant rider
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
                        self.add_competitor(trcno, trteam)
                        if trcno not in ret:
                            ret[trcno] = []
                        ret[trcno].append((trrno, trseries, splitpts))
                    else:
                        _log.debug('Missing rider %s in team %s', member, no)
            else:
                self.add_competitor(cno, team)
                # single rider/all in same team: return original detail
                ret[cno] = ((no, series, pts), )
        else:
            _log.warning('Unknown competitor %s skipped', no, series)
        return ret

    def add_competitor(self, code, name):
        """Add team code to points map if required"""
        if code not in self.ptstally:
            self.ptstally[code] = {
                'name': name,
                'total': 0,
                'detail': [],
            }
        if code not in self.prevpts:
            self.prevpts[code] = 0

    def accumulate_event(self, evno, pmap):
        """Read event details and return true if event was finished"""
        if evno == self.evno:
            _log.warning('Event %r: Self-reference ignored', evno)
            return False
        r = self.meet.get_event(evno, False)
        if r is None:
            _log.warning('Event %r not found for lookup %r', evno,
                         pmap['label'])
            return False
        r.loadconfig()  # now have queryable event handle
        bestn = self.bestindiv
        if r.series.startswith('t'):
            bestn = self.bestteam
        _log.debug('Accumulating best %d places from %s', bestn, evno)
        teamcounts = {}
        ret = False
        if r.finished:
            _log.debug('Event %s finished... result gen..', evno)
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
            ret = True
        else:
            _log.debug('Event %r skipped: not yet finished', evno)
            self.finished = False
            ret = False
        r = None
        return ret

    def recalculate(self):
        """Update internal model."""
        # all riders are re-loaded on recalc
        self.riders.clear()
        self._seriespts.clear()
        self.ptstally = {}
        self.finished = True  # cleared below

        # load pre-meet points tally (starting points)
        self.load_startpts()

        sourcecount = 0
        pmap = self.load_pointsmap(self.bheatpts, 'B Heat')
        for evno in self.bheat.split():
            sourcecount += 1
            self.accumulate_event(evno, pmap)
        pmap = self.load_pointsmap(self.aheatpts, 'A Heat')
        for evno in self.aheat.split():
            sourcecount += 1
            self.accumulate_event(evno, pmap)
        pmap = self.load_pointsmap(self.bfinalpts, 'B Final')
        for evno in self.bfinal.split():
            sourcecount += 1
            self.accumulate_event(evno, pmap)
        pmap = self.load_pointsmap(self.afinalpts, 'A Final')
        for evno in self.afinal.split():
            sourcecount += 1
            self.accumulate_event(evno, pmap)

        aux = []
        sraux = []
        cnt = 0
        for cno, detail in self.ptstally.items():
            cnt += 1
            curtotal = detail['total']
            total = int(curtotal)  # discard fractions on report
            aux.append((-total, cno, cnt, total, detail['name']))
            prevpts = self.prevpts[cno]
            srtval = prevpts + curtotal
            detail['series'] = srtval  # retain fractions in export
            srtotal = int(srtval)  # discard fractions on report
            sraux.append(
                (-srtotal, cno, cnt, srtotal, detail['name'], prevpts))
        if aux:
            aux.sort()
            lv = None
            cnt = 0
            plc = None
            for r in aux:
                cnt += 1
                rname = r[4]
                total = r[3]
                if total != lv:
                    plc = cnt
                lv = total
                nr = (r[1], rname, '', '', '', str(plc), str(total))
                self.riders.append(nr)
            sraux.sort()
            cnt = 0
            plc = None
            for r in sraux:
                cnt += 1
                rname = r[4]
                total = r[3]
                if total != lv:
                    plc = cnt
                lv = total
                nr = (r[1], rname, '', '', '', str(plc), str(total))
                self._seriespts.append(nr)

        if len(self.riders) > 0:  # got at least one result to report
            self.onestart = True

        if self.finished and sourcecount > 0:
            self._standingstat = 'Provisional Result'
            self._status = 'provisional'
        else:
            self._standingstat = 'Standings'
            self._status = 'virtual'
        return

    def do_places(self):
        """Show race result on scoreboard."""
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
        self.resend_current()
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
        self.meet = meet
        self.event = event
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
        self.winopen = ui
        self.placesrc = ''  # leave unused
        self.medals = ''  # leave unused
        self.showevents = ''  # maybe re-used
        self.decisions = []
        self.finished = False
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
        self.seriestally = False
        self.showdetail = False
        self.prelabel = None
        self.predata = None
        self.prevpts = {}  # points after previous round
        self.ptstally = {}  # cached content for the "detail" report
        self._seriespts = []  # series summary line sources
        self._winState = {}  # cache ui settings for headless load/save
        self._startlines = None
        self._reslines = None  # round (meet) result
        self._sreslines = None  # series result if enabled
        self._status = None
        self._detail = None
        self._standingstat = ''
        self._tkcache = {}

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
            self.add_competitor(cno, cname)
        return {cno: ((no, series, pts), )}

    def do_places(self):
        """Show race result on scoreboard."""
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
        self.resend_current()
        return False

    def result_report(self, recurse=True):
        """Individual Result - Don't show detail"""
        ret = []

        # start with the overall result
        self.showcats = True  # override cats for indiv result
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)
        sec.units = 'pt'
        sec.heading = self.event.get_info(showevno=True)
        lapstring = strops.lapstring(self.event['laps'])
        subvec = []
        substr = '\u3000'.join(
            (lapstring, self.event['distance'], self.event['rules'])).strip()
        if substr:
            subvec.append(substr)
        stat = self.standingstr()
        if stat:
            subvec.append(stat)
        if subvec:
            sec.subheading = '\u3000'.join(subvec)

        self._reslines = []
        self._sreslines = []
        sec.lines = []
        tstore = {}
        pcount = 0
        for r in self.riders:
            pcount += 1
            rno = r[COL_NO]
            tsk = rno
            members = None
            dbrno, junk = strops.bibstr2bibser(rno)  # uggh
            rh = None
            rhid = self.meet.rdb.get_id(r[COL_NO])  # rno includes series
            if rhid is not None:
                rh = self.meet.rdb[rhid]
            rname = ''
            rnat = None
            plink = ''
            tlink = []
            rcls = ''
            if rh is not None:
                dbrno = rh['no']
                rname = rh.resname()
                rnat = rh['nation']
                rcls = rh['class']
                if not rcls and self.showcats:
                    rcat = rh.primary_cat()

                teamnames = rh['series'].startswith('t')
                if teamnames:
                    members = rh['members'].split()
                    rno = ''
                    for trno in members:
                        trh = self.meet.rdb.fetch_bibstr(trno)
                        if trh is not None:
                            trname = trh.resname()
                            trinf = trh['class']
                            tlink.append(
                                [None, trno, trname, trinf, None, None, None])
                else:
                    # replace BIB.series with db riderno
                    rno = dbrno

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
                    pcount = int(rank)
                    rank += '.'

            pts = r[COL_MEDAL]

            # suppress rno on printed report when non-numeric
            if not rno.isdigit():
                rno = ''

            tstore[tsk] = {
                'rno': rno,
                'dbrno': dbrno,
                'rname': rname,
                'rnat': rnat,
                'rcls': rcls,
                'tlink': tlink,
                'plink': plink,
                'members': members,
            }
            if pts != '0':  # suppress empty lines
                sec.lines.append([rank, rno, rname, rcls, None, pts, plink])
                self._reslines.append({
                    'rank': pcount,
                    'class': rank,
                    'competitor': dbrno,
                    'nation': rnat,
                    'name': rname,
                    'info': rcls,
                    'result': pts,
                    'members': members,
                })
                if tlink:
                    sec.lines.extend(tlink)
        ret.append(sec)

        # also show series standings if configured and available
        if self.seriestally and self._seriespts:
            secid = 'ev-' + str(self.evno).translate(
                strops.WEBFILE_UTRANS) + '-spts'
            sec = report.section(secid)
            sec.units = 'pt'
            sec.heading = ' '.join((self.event['pref'], 'Series Points'))
            lapstring = strops.lapstring(self.event['laps'])
            subvec = []
            substr = ' '.join((lapstring, self.event['distance'],
                               self.event['rules'])).strip()
            if substr:
                subvec.append(substr)
            stat = self.standingstr()
            if stat:
                subvec.append(stat)
            if subvec:
                sec.subheading = ' - '.join(subvec)

            pcount = 0
            for r in self._seriespts:
                pcount += 1
                tsk = r[COL_NO]
                iob = tstore[tsk]
                rank = ''
                rks = r[COL_PLACE]
                if rks:
                    rank = rks
                    if rank.isdigit():
                        pcount = int(rank)
                        rank += '.'
                pts = str(r[COL_MEDAL])
                if pts != '0':
                    sec.lines.append([
                        rank, iob['rno'], iob['rname'], iob['rcls'], None, pts,
                        iob['plink']
                    ])
                    self._sreslines.append({
                        'rank': pcount,
                        'class': rank,
                        'competitor': iob['dbrno'],
                        'nation': iob['rnat'],
                        'name': iob['rname'],
                        'info': iob['rcls'],
                        'result': pts,
                        'members': iob['members'],
                    })
                    if iob['tlink']:
                        sec.lines.extend(iob['tlink'])
            ret.append(sec)

        if self.showdetail:
            ret.extend(self.detail_report())

        if len(self.decisions) > 0:
            ret.append(self.meet.decision_section(self.decisions))

        return ret
