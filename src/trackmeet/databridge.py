# SPDX-License-Identifier: MIT
"""Databridge structured meet data exchange"""

import logging
import json
from hashlib import sha256
from datetime import date, datetime, UTC
from zoneinfo import ZoneInfo
from contextlib import suppress
from secrets import randbits
import metarace
from metarace import tod
from metarace import strops
from metarace import jsonconfig
from metarace.riderdb import riderdb

_log = logging.getLogger('databr')
_log.setLevel(logging.DEBUG)

# Internal Constants
_CACHEPATH = '.db.cache'  # object hash cache

# "Special" categories for non-championship meets
_NONCHAMPCATS = {
    'W': 'Women',
    'M': 'Men',
    'O': 'Open',
    'T': 'Teams',
}

# Configuration
_CONFIG_SCHEMA = {
    'mtype': {
        'prompt': 'Data Bridge',
        'control': 'section',
    },
    'prefix': {
        'attr': 'prefix',
        'prompt': 'Topic Prefix:',
        'control': 'short',
        'hint': 'MQTT topic prefix for all bridge objects eg: db',
        'default': 'db',
        'defer': True,
    },
    'timezone': {
        'prompt': 'Timezone:',
        'attr': 'timezone',
        'hint': 'Local timezone for meet eg: Australia/Adelaide',
        'defer': True,
        'default': 'UTC',
    },
    'categories': {
        'prompt': 'Categories:',
        'attr': 'categories',
        'hint': 'Meet categories',
        'defer': True,
    },
}


def _colkey(col):
    """Clean column headers and lowercase"""
    return col.strip().lower().replace(' ', '')


def _ornull(text):
    """Return the text, or None if it is an empty string"""
    return text if text else None


def _mkstartlist():
    """Return an empty, ordered startlist object dict"""
    ret = {}
    for k in ('title', 'subtitle', 'info', 'distance', 'laps', 'status',
              'competitionType', 'competitorType', 'competitors'):
        ret[k] = None
    ret['competitors'] = []
    return ret


def _mkresult():
    """Return an empty, ordered result object dict"""
    ret = {}
    for k in ('title', 'subtitle', 'info', 'distance', 'laps', 'status',
              'competitionType', 'competitorType', 'lines', 'units',
              'decisions', 'weather', 'detail', 'startTime'):
        ret[k] = None
    ret['lines'] = []
    ret['decisions'] = []
    ret['detail'] = {}
    return ret


class PublicEncoder(json.JSONEncoder):
    """Encode tod, agg, datetime and dates for lvis use"""

    def default(self, obj):
        if isinstance(obj, tod.tod):
            b = (obj.timeval * 0).as_tuple()
            places = min(-(b.exponent), 5)
            return obj.isostr(places)  # retain truncation of original value
        elif type(obj) is datetime:
            ts = 'seconds'
            if obj.microsecond:
                ts = 'milliseconds'
            return obj.isoformat(timespec=ts)
        elif isinstance(obj, date):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)


class DataBridge():
    """Data Bridge context handler class"""

    def pause(self):
        """Pause message publishing"""
        self._pause = True

    def unpause(self):
        """Un-pause message publishing"""
        self._pause = False

    def loadCategories(self):
        """Load and initialise Category source objects"""
        self._categories.clear()
        self.updateCompetitors()

    def updateHeatHead(self, event, fragment, data):
        """Update and publish a heat head"""

        # ensure object exists on bridge
        if fragment not in self._competitions:
            compObj = {}
            self._competitions[fragment] = compObj
        info = _ornull(event['rules'])

        # prepare export object
        compObj = self._competitions[fragment]
        for k in ('title', 'subtitle', 'label', 'status', 'info', 'events',
                  'distance', 'laps'):
            if k == 'info':
                compObj[k] = info
            elif k in data and data[k]:
                compObj[k] = data[k]
            else:
                if k not in compObj:
                    compObj[k] = None

        meetPath = self.getPath(fragment)
        self._pathSave(meetPath, compObj)

    def updateContestHead(self, event, fragment, data):
        """Update and publish a contest head"""

        # add required entries
        if 'heats' not in data:
            data['heats'] = {}
        info = _ornull(event['rules'])

        # ensure object exists on bridge
        if fragment not in self._competitions:
            compObj = {}
            self._competitions[fragment] = compObj

        # prepare export object
        compObj = self._competitions[fragment]
        for k in ('title', 'subtitle', 'label', 'status', 'info', 'heats',
                  'events', 'distance', 'laps'):
            if k == 'info':
                compObj[k] = info
            elif k in data and data[k]:
                compObj[k] = data[k]
            else:
                if k not in compObj:
                    compObj[k] = None

        meetPath = self.getPath(fragment)
        self._pathSave(meetPath, compObj)

    def updatePhaseHead(self, event, fragment, data):
        """Update and publish a phase head"""

        # add required entries
        if 'contests' not in data:
            data['contests'] = {}
        info = _ornull(event['rules'])

        # ensure object exists on bridge
        if fragment not in self._competitions:
            compObj = {}
            self._competitions[fragment] = compObj

        # prepare export object
        compObj = self._competitions[fragment]
        for k in ('title', 'subtitle', 'info', 'status', 'contests', 'events',
                  'distance', 'laps'):
            if k == 'info':
                compObj[k] = info
            elif k in data and data[k]:
                compObj[k] = data[k]
            else:
                if k not in compObj:
                    compObj[k] = None

        meetPath = self.getPath(fragment)
        self._pathSave(meetPath, compObj)

    def updateCompetitionHead(self, event, fragment, data):
        """Update and publish a competition head"""

        # update category entry
        category = data['category']
        competition = data['competition']
        catObj = self._categories[category]
        catObj['competitions'][competition] = data['title']

        # add required entries
        data['label'] = _ornull(event['info'])
        if 'phases' not in data:
            data['phases'] = {}
        if 'warnings' not in data:
            data['warnings'] = {}
        if 'records' not in data:
            data['records'] = {}

        # ensure object exists on bridge
        if fragment not in self._competitions:
            compObj = {}
            self._competitions[fragment] = compObj

        # prepare export object
        compObj = self._competitions[fragment]
        for k in ('label', 'competitorType', 'category', 'title', 'status',
                  'phases', 'events', 'warnings', 'records'):
            if k in data and data[k]:
                compObj[k] = data[k]
            else:
                if k not in compObj:
                    compObj[k] = None

        meetPath = self.getPath(fragment)
        self._pathSave(meetPath, compObj)

    def _updateResultLine(self, line, topn=None):
        """Return a patched result line object"""
        if line is None:
            return None
        obj = {
            'rank': None,
            'class': None,
            'competitor': None,
            'nation': None,
            'name': None,
            'pilot': None,
            'members': None,
            'info': None,
            'badges': [],
            'result': None,
            'extra': None,
        }
        # overwrite any provided non-empty values
        qual = False
        for k in obj:
            # update value
            if k in line and line[k]:
                if k == 'members':
                    members = []
                    for m in line[k]:
                        mno, junk = strops.bibstr2bibser(m)
                        members.append(mno)
                    obj[k] = members
                elif k == 'badges':
                    if isinstance(line[k], (set, list, tuple)):
                        obj[k] = sorted(set(line[k]))
                else:
                    obj[k] = line[k]

            # check qualifying - TODO revisit this in event
            #if k == 'rank' and topn and obj[k]:
            #rank = obj[k]
            #if rank <= topn:
            #qual = True
            #elif k == 'badges':
            #if qual and 'qualified' not in obj['badges']:
            #obj['badges'].append('qualified')
        return obj

    def _lookupCompetitor(self, cid, event):
        """Look up a competitor ID and fill in a basic result line"""
        ret = None
        catComp = event.get_catcomp()
        if catComp in self._competitions:
            category = event['category']
            compObj = self._competitions[catComp]
            competitorType = compObj['competitorType']
            if category in self._categories:
                cref = None
                competitors = self._categories[category]['competitors']
                if competitorType == 'rider':
                    if cid in competitors['riders']:
                        cref = competitors['riders'][cid]
                        ret = {
                            'competitor': cref['number'],
                            'nation': cref['nation'],
                            'name': cref['resname'],
                            'info': cref['class'],
                        }
                elif competitorType == 'team':
                    if cid in competitors['teams']:
                        cref = competitors['teams'][cod]
                        ret = {
                            'competitor': cref['code'],
                            'nation': cref['nation'],
                            'name': cref['name'],
                            'members': cref['members'],
                        }
                elif competitorType == 'pair':
                    if cid in competitors['pairs']:
                        cref = competitors['pairs'][cod]
                        ret = {
                            'competitor': cref['number'],
                            'nation': cref['nation'],
                            'name': cref['name'],
                        }
                else:
                    _log.debug('Missing info for competitor %s', cid)
            else:
                _log.debug('Missing info for category %s', category)
        else:
            _log.debug('Missing info for catComp %s', catComp)

        return ret

    def updateResultLines(self, event, fragment, lines):
        """Scan result lines and patch values"""
        catComp = event.get_catcomp()
        topn = _ornull(event['topn'])

        # scan lines and transfer to result
        ret = []
        for c in lines:
            if isinstance(c, str):
                # promote competitor ID to line
                c = self._lookupCompetitor(c, event)
            cno = None
            if 'competitor' in c:
                cno = _ornull(c['competitor'])
            if cno is None:
                _log.debug('Missing competitor no %r for result %s', c,
                           fragment)
                continue
            ret.append(self._updateResultLine(c, topn))
        return ret

    def updateStartLines(self, event, fragment, competitors):
        """Scan starter list and patch all values"""
        catComp = event.get_catcomp()

        # fetch qualifying entry if it exists
        qual = None
        if catComp in self._qualifying:
            qual = self._qualifying[catComp]

        # scan competitors and transfer to start list
        ret = []
        for c in competitors:
            cno = None
            if 'competitor' in c:
                cno = _ornull(c['competitor'])
            if cno is None:
                _log.debug('Missing competitor no %r for %s', c, fragment)
                continue
            obj = {
                'competitor': None,
                'nation': None,
                'name': None,
                'pilot': None,
                'members': None,
                'info': None,
                'badges': [],
                'qualRank': None,
                'qualPlace': None,
                'qualTime': None,
            }

            # pre-fill qualifying info
            if qual and cno in qual:
                qualObj = qual[cno]
                for k in ('qualRank', 'qualPlace', 'qualTime'):
                    obj[k] = qualObj[k]

            # overwrite any provided non-empty values
            for k in obj:
                if k in c and c[k]:
                    obj[k] = c[k]
            ret.append(obj)
        return ret

    def updateStartlist(self, event, fragment, data):
        """Fill and publish a result object for the provided fragment"""
        # enforce display of phase rules on startlist
        dataObj = {
            'title': None,
            'subtitle': None,
            'info': _ornull(event['rules']),
            'distance': None,
            'laps': None,
            'status': None,
            'competitionType': None,
            'competitorType': None,
            'competitors': [],
        }
        for k in dataObj:
            if k == 'competitors':
                if k in data:
                    dataObj[k] = self.updateStartLines(event, fragment,
                                                       data[k])
            elif k == 'info':
                pass
            elif k in data and data is not None:
                dataObj[k] = data[k]

        meetPath = self.getPath(fragment, 'startlist')
        self._pathSave(meetPath, dataObj)

    def updateResult(self, event, fragment, data):
        """Fill and publish a result object for the provided fragment"""
        dataObj = {
            'title': None,
            'subtitle': None,
            'info': None,
            'distance': None,
            'laps': None,
            'status': None,
            'competitionType': None,
            'competitorType': None,
            'lines': [],
            'units': None,
            'decisions': [],
            'weather': None,
            'detail': {},
            'startTime': None,
        }
        for k in dataObj:
            if k == 'lines':
                if k in data:
                    dataObj[k] = self.updateResultLines(
                        event, fragment, data[k])
            elif k in data and data is not None:
                if k == 'startTime':
                    if isinstance(data['startTime'], tod.tod):
                        data['startTime'] = tod.mergedate(data['startTime'],
                                                          micros=True)
                dataObj[k] = data[k]

        meetPath = self.getPath(fragment, 'result')
        self._pathSave(meetPath, dataObj)

    def updateFragment(self, event, fragment, data={}):
        """Update and publish a fragment"""

        # ensure event meta matches the claimed CAT/comp
        path = fragment.split('/')
        plen = len(path)
        catComp = event.get_catcomp()
        if catComp is None:
            _log.debug('Missing category or competition: %s', fragment)
        chkComp = '/'.join(path[0:2])
        if chkComp != catComp:
            _log.warning('Data/fragment mismatch ignored: %s not in %s',
                         fragment, catComp)
            return

        # ensure there is a category to write into
        category = _ornull(event['category'])
        if category not in self._categories:
            _log.debug('Missing cat %r for %s', category, fragment)
            self.addCategory(category)

        # patch the fragment elements
        data['category'] = category
        data['competition'] = _ornull(event['competition'])
        data['phase'] = _ornull(event['phase'])
        data['contest'] = _ornull(event['contest'])
        data['heat'] = _ornull(event['heat'])

        # patch event information
        data['title'] = event.get_info()
        #if 'info' not in data:
        #data['info'] = _ornull(event['rules'])
        data['competitorType'] = event.competitor_type()
        data['laps'] = _ornull(event['laps'])
        data['distance'] = _ornull(event['distance'])
        if 'events' not in data:
            data['events'] = {}
        if 'status' not in data:
            data['status'] = None

        # publish fragment of the correct type
        if plen == 2:  # CAT/comp
            self.updateCompetitionHead(event, fragment, data)
        elif plen == 3:  # CAT/comp/phase
            self.updatePhaseHead(event, fragment, data)
        elif plen == 4:  # CAT/comp/phase/contest
            self.updateContestHead(event, fragment, data)
        elif plen == 5:  # CAT/comp/phase/contest/heat
            self.updateHeatHead(event, fragment, data)
        else:
            _log.debug('Invalid fragment ignored: %s', fragment)

        self.updateStartlist(event, fragment, data)
        self.updateResult(event, fragment, data)

    def updateCategories(self):
        """Publish category objects"""
        for c in self._catlist:
            self.updateCategory(c)

    def addCategory(self, cat):
        """Add category entry"""
        if cat not in self._categories:
            self._categories[cat] = {
                'label': None,
                'competitions': {},
                'competitors': {},
            }
            compObj = self._categories[cat]['competitors']
            for ctype in ('riders', 'teams', 'pairs', 'pilots'):
                compObj[ctype] = {}
        if (cat, 'cat') in self._m.rdb:
            self._categories[cat]['label'] = self._m.rdb[(cat, 'cat')]['title']
        elif cat in _NONCHAMPCATS:
            self._categories[cat]['label'] = _NONCHAMPCATS[cat]
        if cat not in self._catlist:
            _log.debug('Adding category %s', cat)
            self._catlist.append(cat)

    def getFragment(self, fragment, event):
        """Prepare an updated fragment object and return"""
        pass

    def updateCategory(self, cat):
        """Update and publish the category object"""
        if not cat:
            _log.debug('Ignored empty cat')
            return

        self.addCategory(cat)

        # write out the category stub
        catObj = self._categories[cat]
        dataObj = {
            'label': catObj['label'],
            'competitions': catObj['competitions'],
        }
        meetPath = self.getPath(cat)
        self._pathSave(meetPath, dataObj)

        # write out the competitors
        meetPath = self.getPath(cat, 'competitors')
        self._pathSave(meetPath, self._categories[cat]['competitors'])

    def addCompetitor(self, c):
        """Add competitor to data source"""
        cat = c.primary_cat()
        if not cat:
            cat = 'O'  # put unassigned competitors in Open cat
        sportClass = c['class']
        if cat == 'PARA' and not sportClass:
            # pick off first subcat as sport class
            for ecat in c.get_cats():
                if ecat != 'PARA':
                    sportClass = ecat
                    break
            else:
                _log.info('Para competitor without sport class: %s',
                          c.resname_bib())
        if cat not in self._categories:
            _log.debug('Adding cat = %r for competitor %s', cat, c.resname())
            self.addCategory(cat)

        compObj = self._categories[cat]['competitors']
        ser = c['series'].lower()
        cno = c['no']
        if ser == 'pilot':  # Para Pilot
            compObj['pilots'][cno] = {
                'number': cno,
                'class': _ornull(sportClass),
                'first': _ornull(c['first'].strip().title()),
                'last': _ornull(c['last'].strip().upper()),
                'nation': _ornull(c['nation']),
                'uciid': _ornull(c['uciid']),
                'dob': _ornull(c['dob']),
                'state': _ornull(c['data']),
                'org': _ornull(c['org']),
                'resname': _ornull(c.resname()),
            }
        elif ser.startswith('tm'):  # Madison pair
            blackRid = None
            redRid = None
            for m in c['members'].split():
                lr = self._m.rdb.fetch_bibstr(m)  # creates new if not found
                if blackRid is None:
                    blackRid = lr['no']
                elif redRid is None:
                    redRid = lr['no']
                else:
                    _log.debug('Extra madison members ignored for %s',
                               c.resname_bib())
                    break
            compObj['pairs'][cno] = {
                'number': cno,
                'name': _ornull(c['first'].strip()),
                'nation': _ornull(c['nation']),
                'state': _ornull(c['data']),
                'black': blackRid,
                'red': redRid,
                'org': _ornull(c['org']),
                'resname': _ornull(c.resname()),
            }
        elif ser.startswith('t'):  # Team Entry
            members = []
            for m in c['members'].split():
                lr = self._m.rdb.fetch_bibstr(m)  # creates new if not found
                members.append(lr['no'])
            compObj['teams'][cno] = {
                'code': cno,
                'name': _ornull(c['first'].strip()),
                'nation': _ornull(c['nation']),
                'state': _ornull(c['data']),
                'members': members,
                'org': _ornull(c['org']),
                'resname': _ornull(c.resname()),
            }
        else:  # Rider
            compObj['riders'][cno] = {
                'number': cno,
                'class': _ornull(sportClass),
                'first': _ornull(c['first'].strip().title()),
                'last': _ornull(c['last'].strip().upper()),
                'nation': _ornull(c['nation']),
                'uciid': _ornull(c['uciid']),
                'dob': _ornull(c['dob']),
                'state': _ornull(c['data']),
                'org': _ornull(c['org']),
                'resname': _ornull(c.resname()),
            }

    def updateCompetitors(self):
        """Update source data for competitors"""
        for rid in self._m.rdb:
            r = self._m.rdb[rid]
            if r['series'] == 'cat':
                _log.debug('Add category %s for cat entry %s', r['id'],
                           r.resname())
                self.addCategory(r['id'])
            elif r['series'] and r['series'].lower() in ('series', 'spare',
                                                         'ds'):
                pass
            else:
                if r['no']:
                    self.addCompetitor(r)

    def updateEventIndex(self):
        """Update the event index object and publish"""
        dataObj = {}
        for k, e in self._events.items():
            dataObj[k] = {}
            dstObj = dataObj[k]
            for k in (
                    'title',
                    'subtitle',
                    'info',
                    'extra',
                    'distance',
                    'laps',
                    'session',
                    'category',
                    'competition',
                    'phase',
                    'fragments',
                    'startTime',
            ):
                if k in e:
                    dstObj[k] = e[k]
                else:
                    dstObj[k] = None

        # write out the event index
        meetPath = self.getPath('events')
        self._pathSave(meetPath, dataObj)

    def _getDateTime(self, isostr):
        ret = None
        with suppress(Exception):
            ret = datetime.fromisoformat(isostr)
        return ret

    def updateSessions(self):
        """Update Schedule of events and publish"""
        self._sessions.clear()
        self._events.clear()
        self._competitions.clear()

        # walk the event listing (from meet)
        for meeteh in self._m.edb:
            sessionid = _ornull(meeteh['session'])
            fragment = meeteh.get_fragment()

            # ensure session object exists
            if sessionid:
                if sessionid not in self._sessions:
                    self._sessions[sessionid] = {
                        'title': self._meet['title'],
                        'subtitle': self._meet['subtitle'],
                        'location': self._meet['location'],
                        'label': None,
                        'startTime': None,
                        'endTime': None,
                        'events': {},
                        'finals': {},
                    }

            if meeteh['type'] == 'session':
                # Special case: session marker
                sessOb = self._sessions[sessionid]
                sessOb['startTime'] = meeteh['start']
                sessOb['endTime'] = meeteh['endtime']
                sessOb['label'] = _ornull(meeteh['prefix'])
            else:
                # fragment, event, break or something else
                evid = meeteh.get_evno()
                phase = _ornull(meeteh['phase'])
                category = _ornull(meeteh['category'])
                competition = _ornull(meeteh['competition'])
                evtObj = None

                # ensure category exists (allows anon/no competitor)
                if category and category not in self._categories:
                    self.addCategory(category)

                # add event to index if flagged
                if meeteh['index']:
                    if evid not in self._events:
                        evtObj = {
                            'title':
                            _ornull(meeteh['prefix']),  # should be title
                            'subtitle':
                            _ornull(meeteh['info']),  # should be subtitle
                            'info': _ornull(meeteh['rule']),
                            'distance': _ornull(meeteh['dist']),
                            'laps': _ornull(meeteh['laps']),
                            'session': sessionid,
                            'category': category,
                            'competition': competition,
                            'phase': phase,
                            'fragments': [],
                            'startTime': meeteh['start'],
                        }
                        self._events[evid] = evtObj
                    evtObj = self._events[evid]

                # update links if event contributes to data bridge
                if fragment:
                    evtInfo = meeteh.get_info()
                    evtLabel = _ornull(meeteh['info'])
                    catComp = meeteh.get_catcomp()  # ensured by fragment

                    # TEMP: choose ctype by series
                    competitorType = meeteh.competitor_type()

                    # ensure competition is listed in category stub
                    catObj = self._categories[category]
                    if competition not in catObj['competitions']:
                        catObj['competitions'][competition] = evtLabel
                    # ensure CAT/comp object exists on bridge
                    if catComp not in self._competitions:
                        compObj = {
                            'label': evtLabel,
                            'competitorType': competitorType,
                            'category': category,
                            'title': evtInfo,
                            'status': None,
                            'phases': {},
                            'events': {},
                            'warnings': {},
                            'records': {},
                        }
                        self._competitions[catComp] = compObj
                    compObj = self._competitions[catComp]

                    # fill in compObj details
                    if phase and phase not in compObj['phases']:
                        compObj['phases'][phase] = evtLabel

                    # add fragment to evtObj if on schedule
                    if evtObj is not None:
                        if fragment not in evtObj['fragments']:
                            evtObj = self._events[evid]
                            evtObj['fragments'].append(fragment)
                        if evid and evid not in compObj['events']:
                            compObj['events'][evid] = evtLabel

                        # add event & final to session entry
                        if sessionid:
                            sessOb = self._sessions[sessionid]
                            if evid not in sessOb['events']:
                                sessOb['events'][evid] = evtInfo
                            if phase == 'final':
                                if catComp not in sessOb['finals']:
                                    sessOb['finals'][catComp] = evtInfo

        self.updateEventIndex()

        # publish the session objects
        for k, v in self._sessions.items():
            meetPath = self.getPath(k)
            self._pathSave(meetPath, v)

        # publish CAT/comp objects (these may be overwritten by ev handlers)
        for k, v in self._competitions.items():
            meetPath = self.getPath(k)
            self._pathSave(meetPath, v)

    def getPath(self, *arg):
        """Assemble a compressed path from args"""
        rv = [self._base]
        for a in arg:
            if a:
                rv.append(a)
        return '/'.join(rv)

    def clearCurrent(self, event=None, fragment=None):
        """Reset current object"""
        self._current.clear()

        if event is not None and fragment is not None:
            # ensure event meta matches the claimed CAT/comp
            path = fragment.split('/')
            plen = len(path)
            catComp = event.get_catcomp()
            if catComp is None:
                _log.debug('Missing category or competition: %s', fragment)
            chkComp = '/'.join(path[0:2])
            if chkComp != catComp:
                _log.debug('Data/fragment mismatch ignored: %s not in %s',
                           fragment, catComp)
                return
            meetPath = self.getPath(fragment)

            # pre-fill the static elements
            self._current['path'] = meetPath
            self._current['title'] = event.get_info()
            self._current['info'] = _ornull(event['rules'])
            self._current['event'] = event.get_evno()
            self._current['session'] = _ornull(event['session'])
            self._current['competitorType'] = event.competitor_type()
            self._current['category'] = path[0]
            self._current['competition'] = path[1]
            self._current['phase'] = None
            self._current['eventStart'] = event['start']
            if len(path) > 2 and path[2]:
                self._current['phase'] = path[2]
            self._current['contest'] = None
            if len(path) > 3 and path[3]:
                self._current['contest'] = path[3]
            self._current['heat'] = None
            if len(path) > 4 and path[4]:
                self._current['heat'] = path[4]
            self._current['laps'] = _ornull(event['laps'])
            self._current['distance'] = _ornull(event['distance'])

    def sendCurrent(self, event=None, fragment=None, data={}):
        """Repopulate current object from provided context"""
        if event is not None and fragment is not None:
            self.clearCurrent(event, fragment)

        # upgrade ToD to Datetime
        stod = None
        if 'startTime' in data:
            if isinstance(data['startTime'], tod.tod):
                stod = data['startTime']
                data['startTime'] = tod.mergedate(data['startTime'],
                                                  micros=True)
        etod = None
        if 'endTime' in data:
            if isinstance(data['endTime'], tod.tod):
                etod = data['endTime']
                data['endTime'] = tod.mergedate(data['endTime'], micros=True)
        if stod and etod:
            data['elapsed'] = (etod - stod).truncate(3)

        # fill in competitor information as result lines
        topn = None
        if event is not None:
            topn = _ornull(event['topn'])
        for k in ('competitorA', 'competitorB', 'eliminated'):
            if k in data:
                csrc = data[k]
                if isinstance(csrc, str):
                    # promote competitor ID to line
                    csrc = self._lookupCompetitor(csrc, event)
                data[k] = self._updateResultLine(csrc, topn)

        # override values provided by the data object
        for k in ('status', 'title', 'subtitle', 'session', 'info',
                  'competitionType', 'eventStart', 'startTime', 'endTime',
                  'elapsed', 'competitorA', 'labelA', 'timeA', 'downA',
                  'rankA', 'infoA', 'competitorB', 'labelB', 'timeB', 'downB',
                  'rankB', 'infoB', 'eliminated', 'remain', 'toGo', 'record',
                  'noLaps'):
            if k in data and data[k]:
                self._current[k] = data[k]

        # publish object
        self.updateCurrent()

    def updateCurrent(self):
        """Update current object and publish"""

        # pre-fill weather with current observation
        self._current['weather'] = self._m.get_weather()

        # import values from object source in order
        dataObj = {}
        for k in ('path', 'status', 'title', 'subtitle', 'info', 'event',
                  'session', 'category', 'competition', 'phase', 'contest',
                  'heat', 'competitorType', 'competitionType', 'eventStart',
                  'startTime', 'endTime', 'elapsed', 'competitorA', 'labelA',
                  'timeA', 'downA', 'rankA', 'infoA', 'competitorB', 'labelB',
                  'timeB', 'downB', 'rankB', 'infoB', 'eliminated', 'remain',
                  'toGo', 'laps', 'distance', 'record', 'weather'):

            if k in self._current:
                dataObj[k] = self._current[k]
            else:
                dataObj[k] = None

        # override "auto" laps to go for bunch racs
        if dataObj['competitionType'] == 'bunch':
            if 'noLaps' not in self._current:
                if self._m.lapscore:
                    dataObj['toGo'] = self._m.lapscore

        meetPath = self.getPath('current')
        self._pathSave(meetPath, dataObj)

    def updateMeet(self):
        """Update and publish the base meet object"""

        # update static information
        self._meet['timezone'] = str(self._tz)
        self._meet['title'] = _ornull(self._m.title)
        self._meet['subtitle'] = _ornull(self._m.subtitle)
        self._meet['organiser'] = _ornull(self._m.organiser)
        self._meet['location'] = _ornull(self._m.document)
        self._meet['locationCode'] = _ornull(self._m.facility)
        self._meet['pcp'] = _ornull(self._m.pcp)
        self._meet['date'] = _ornull(self._m.date)

        # load category stubs and competitor data
        self.loadCategories()

        # re-read schedule of events, competitions and base fragments
        self.updateSessions()

        # export category objects
        self.updateCategories()

        # populate meet object
        dataObj = {}
        for k in ('title', 'subtitle', 'organiser', 'location', 'locationCode',
                  'pcp', 'date', 'timezone', 'startDate', 'endDate',
                  'schedule', 'categories'):
            if k in self._meet:
                dataObj[k] = self._meet[k]
            else:
                dataObj[k] = None

        # fill in category labels
        dataObj['categories'] = {}
        cats = dataObj['categories']
        for k, v in self._categories.items():
            cats[k] = v['label']

        # fill in session labels and dates
        first = None
        last = None
        dataObj['schedule'] = {}
        sessions = dataObj['schedule']
        for k, v in self._sessions.items():
            sessions[k] = v['label']
            if v['startTime'] is not None:
                sdate = v['startTime'].date()
                if first is None:
                    first = sdate
                last = sdate
        dataObj['startDate'] = first
        dataObj['endDate'] = last

        # publish object
        self._pathSave(self._base, dataObj)

    def flushAll(self):
        """Unpublish all cached objects"""
        self._uncache.update(self._cache)
        for meetpath in self._uncache:
            self._pathDelete(meetpath)
        self._uncache.clear()
        self._cache.clear()

    def update(self):
        """Update the root-level meet objects"""
        self.updateMeet()
        self.updateCurrent()

    def load(self):
        """Initialise internal context"""
        _log.debug('Load')
        cr = jsonconfig.config()
        cr.add_section('databridge', _CONFIG_SCHEMA)
        cr.merge(metarace.sysconf, 'databridge')

        zone = None
        with suppress(Exception):
            zone = ZoneInfo(cr.get_value('databridge', 'timezone'))
        if zone is not None:
            self._tz = zone
        else:
            _log.debug('Invalid timezone, using UTC')
            self._tz = UTC

        # load topic prefix from sysconf
        self._prefix = _ornull(cr.get_value('databridge', 'prefix'))

        # load basepath from meet
        self._base = _ornull(self._m.eventcode)
        if self._base is None:
            _log.debug('Invalid meet code, using "meet"')
            self._base = 'meet'

        # load tracklen from meet
        self._tracklen = None
        with suppress(Exception):
            self._tracklen = self._m.tracklen_n / self._m.tracklen_d
            _log.debug('Track lap length = %r\u2006m', self._tracklen)

        # load desired competition categories
        self._catlist.clear()
        with suppress(Exception):
            catlist = []
            cl = cr.get_value('databridge', 'categories').split()
            for c in cl:
                if c and c not in catlist:
                    catlist.append(c)
            self._catlist.extend(catlist)

        # reload cache
        self._cache.clear()
        with suppress(Exception):
            with open(_CACHEPATH) as f:
                cache = json.load(f)
                if isinstance(cache, dict):
                    for k, v in cache.items():
                        if isinstance(v, str):
                            self._cache[k] = v

    def save(self):
        """Save cache and context to disk"""
        _log.debug('Save')
        with suppress(Exception):
            with metarace.savefile(_CACHEPATH) as f:
                json.dump(self._cache, f)

    def __init__(self, meet):
        self._m = meet  # meet handle
        self._tz = UTC
        self._prefix = None
        self._base = 'meet'
        self._tracklen = None
        self._catlist = []
        self._cache = {}
        self._uncache = set()
        self._meet = {}  # meet data object source
        self._categories = {}  # cat data object source
        self._sessions = {}  # session data object source
        self._events = {}  # event index object source
        self._current = {}  # current object data source
        self._competitions = {}  # CAT/comp object sources
        self._results = {}  # ?? required?
        self._startlists = {}  # ?? required?
        self._qualifying = {}  # filled by result updates
        self._pause = False

    def _pathDelete(self, path):
        """Remove path object"""
        _log.debug('Remove %s from cache', path)
        if path in self._cache:
            del (self._cache[path])
        if not self._pause:
            if self._prefix:
                path = '/'.join((self._prefix, path))
            self._m.announce.publish(message=None,
                                     topic=path,
                                     qos=1,
                                     retain=True)

    def _pathSave(self, path, dataObj):
        """Serialize path object and publish to mqtt"""
        if self._pause:
            return False

        # remove path from uncache if present
        if path in self._uncache:
            self._uncache.remove(path)

        # check hash before adding timestamp
        pt = json.dumps(dataObj, cls=PublicEncoder).encode('ascii')
        dt = sha256(pt, usedforsecurity=False).hexdigest()
        if path in self._cache and self._cache[path] == dt:
            return False

        self._cache[path] = dt
        nt = datetime.now(tz=self._tz)
        dataObj['serial'] = int(nt.timestamp())
        dataObj['updated'] = nt
        msg = json.dumps(dataObj, cls=PublicEncoder)

        # publish to MQTT
        if self._prefix:
            path = '/'.join((self._prefix, path))
        self._m.announce.publish(message=msg, topic=path, qos=1, retain=True)
        return True
