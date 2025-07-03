# SPDX-License-Identifier: MIT
"""CSV Event Listing."""

import logging
import os
import csv

import metarace
from metarace import strops

_log = logging.getLogger('eventdb')
_log.setLevel(logging.DEBUG)

# default event values (if not empty string)
_EVENT_DEFAULTS = {
    'evid': None,  # empty not allowed
    'resu': True,
    'inde': False,
    'prog': False,
    'dirt': False,
    'plac': None,
    'topn': None,
    'laps': None,
}

# event column heading and key mappings
_EVENT_COLUMNS = {
    'sess': 'Session',
    'evid': 'Event ID',
    'refe': 'Reference No',
    'evov': 'Override No',
    'type': 'Type Handler',
    'seri': 'Series',
    'pref': 'Prefix',
    'info': 'Information',
    'resu': 'Result?',
    'inde': 'Index?',
    'prog': 'Program?',
    'depe': 'Depends On',
    'auto': 'Auto Starters',
    'plac': 'Placeholders',
    'topn': 'Qualifiers',
    'laps': 'Laps',
    'dist': 'Distance',
    'phas': 'Phase Rules',
    'spon': 'Sponsor',
    'priz': 'Prizemoney',
    'reco': 'Record',
    'dirt': 'Dirty?',
}

# Column strings lookup, and legacy alterations
_ALT_COLUMNS = {
    'id': 'evid',
    'event id': 'evid',
    'no': 'evid',
    'printed': 'prog',  # legacy "Printed Program"
    'progress': 'phas',  # legacy "Progression Rules"
    'qualifie': 'topn',
    'qualify': 'topn',
    'top n qu': 'topn',
    'starters': 'auto',  # legacy "Starters"
    'override': 'evov',
    'evoverri': 'evov',  # legacy "EVOverride"
}


# Transition pre 1.13.3 event db to new format
def _clean_autofield(starters):
    ret = starters.lower()
    if ret:
        if ':' in ret:
            if ret.startswith('auto'):
                ret = ret[4:].strip()
                _log.debug('Updated old-style autospec to %r', ret)
        else:
            ret = ''
            _log.debug('Removed old-style starters %r from eventdb', starters)
    return ret


# for any non-strings, types as listed
_EVENT_COLUMN_CONVERTERS = {
    'resu': strops.confopt_bool,
    'inde': strops.confopt_bool,
    'prog': strops.confopt_bool,
    'dirt': strops.confopt_bool,
    'plac': strops.confopt_posint,
    'laps': strops.confopt_posint,
    'topn': strops.confopt_posint,
    'auto': _clean_autofield,
}

_DEFAULT_COLUMN_ORDER = (
    'sess',
    'evid',
    'refe',
    'evov',
    'type',
    'seri',
    'pref',
    'info',
    'laps',
    'dist',
    'resu',
    'inde',
    'prog',
    'depe',
    'auto',
    'plac',
    'topn',
    'phas',
    'spon',
    'priz',
    'reco',
    'dirt',
)

_EVENT_ALIASES = {
    'time trial': 'indiv tt',
    'pursuit': 'indiv pursuit',
    'sprint derby': 'sprint',
    'bunch race': 'race',
    'sprint best of 3': 'sprint final',
    'wheelrace': 'handicap',
}

_EVENT_TYPES = {
    'flying 200': 'Flying 200m',
    'flying lap': 'Flying Lap',
    'indiv tt': 'Time Trial',
    'team sprint': 'Team Sprint',
    'team sprint race': 'Team Sprint Race',
    'indiv pursuit': 'Pursuit',
    'pursuit race': 'Pursuit Race',
    'team pursuit': 'Team Pursuit',
    'team pursuit race': 'Team Pursuit Race',
    'scratch': 'Scratch',
    'points': 'Points',
    'madison': 'Madison',
    'omnium': 'Omnium',
    'tempo': 'Tempo',
    'progressive': 'Progressive',
    'classification': 'Classification',
    'break': 'Break',
    'sprint round': 'Sprint Round',
    'sprint final': "Sprint 'of 3",
    'sprint': 'Sprint Derby',
    'keirin': 'Keirin',
    'motorpace': 'Motorpace',
    'handicap': 'Wheelrace',
    'elimination': 'Elimination',
    'race': 'Bunch Race',
    'hour': 'Hour Record',
    #'competition': 'Competition',
    #'aggregate': 'Points Aggregate',
}

_CONFIG_SCHEMA = {
    'sess': {
        'prompt': 'Session ID:',
        'control': 'short',
        'attr': 'sess',
        'defer': True,
        'default': '',
        'hint': 'Session on schedule of events',
    },
    'evid': {
        'prompt': 'Event ID:',
        'control': 'short',
        'attr': 'evid',
        'defer': True,
        'default': '',
        'hint': 'Unique event ID on program of events',
    },
    'refe': {
        'prompt': 'Reference No:',
        'control': 'short',
        'attr': 'refe',
        'defer': True,
        'default': '',
        'hint': 'Competition/classification this event belongs to',
    },
    'evov': {
        'prompt': 'Override No:',
        'control': 'short',
        'attr': 'evov',
        'defer': True,
        'default': '',
        'hint': 'Override displayed event number on reports',
    },
    'seri': {
        'prompt': 'Series:',
        'control': 'short',
        'attr': 'seri',
        'defer': True,
        'default': '',
        'hint': 'Competitor number series',
    },
    'type': {
        'prompt': 'Type Handler:',
        'control': 'choice',
        'options': _EVENT_TYPES,
        'attr': 'type',
        'defer': True,
        'default': '',
    },
    'pref': {
        'prompt': 'Prefix:',
        'attr': 'pref',
        'defer': True,
        'default': '',
        'hint': 'Event category, competition eg: Men Elite Sprint',
    },
    'info': {
        'prompt': 'Information:',
        'attr': 'info',
        'defer': True,
        'default': '',
        'hint': 'Event phase, contest, heat eg: Gold Final Heat 2',
    },
    'laps': {
        'prompt': 'Lap Count:',
        'control': 'short',
        'type': 'int',
        'attr': 'laps',
        'defer': True,
        'hint': 'Event distance in laps',
    },
    'dist': {
        'prompt': 'Distance text:',
        'attr': 'dist',
        'defer': True,
        'default': '',
        'hint': 'Event distance with units',
    },
    'resu': {
        'prompt': 'Include in:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Results?',
        'attr': 'resu',
        'defer': True,
        'default': True,
        'hint': 'Include event result in exported result list',
    },
    'inde': {
        'prompt': '',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Event Index?',
        'attr': 'inde',
        'defer': True,
        'default': False,
        'hint': 'Include event on index of events',
    },
    'prog': {
        'prompt': '',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Printed Program?',
        'attr': 'prog',
        'defer': True,
        'default': False,
        'hint': 'Include event in printed program',
    },
    'depe': {
        'prompt': 'Depends on:',
        'attr': 'depe',
        'defer': True,
        'default': '',
        'hint': 'List of other events this event depends on for export',
    },
    'auto': {
        'prompt': 'Auto Starters:',
        'attr': 'auto',
        'defer': True,
        'default': '',
        'hint': 'Load starters from results of other events',
    },
    'plac': {
        'prompt': 'Placeholders:',
        'control': 'short',
        'type': 'int',
        'attr': 'plac',
        'defer': True,
        'hint': 'Count of riders expected to qualify for this event',
    },
    'topn': {
        'prompt': 'Qualifiers:',
        'control': 'short',
        'type': 'int',
        'attr': 'topn',
        'defer': True,
        'hint': 'Number of qualifiers to next phase of competition',
    },
    'phas': {
        'prompt': 'Phase rules:',
        'attr': 'phas',
        'defer': True,
        'default': '',
        'hint':
        'Short description of progression to next phase of competition',
    },
    'spon': {
        'prompt': 'Sponsor:',
        'attr': 'spon',
        'defer': True,
        'default': '',
        'hint': 'Event sponsor, displayed in section footer',
    },
    'priz': {
        'prompt': 'Prizemoney:',
        'attr': 'priz',
        'defer': True,
        'default': '',
        'hint': 'Space separated list of prizemoney',
    },
    'reco': {
        'prompt': 'Record text:',
        'attr': 'reco',
        'defer': True,
        'default': '',
        'hint': 'Text of current record holder',
    },
    'dirt': {
        'prompt': 'Status:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Dirty?',
        'attr': 'dirt',
        'defer': True,
        'hint': 'Re-load dependent events on next export',
    },
}


def event_type(name):
    """Return the event type for the name given"""
    name = name.lower().replace('_', '').strip()
    if name in _EVENT_ALIASES:
        name = _EVENT_ALIASES[name]
    if name not in _EVENT_TYPES:
        name = 'race'
    return name


def colkey(colstr=''):
    """Convert a column header string to a colkey."""
    col = colstr[0:8].strip().lower()
    if col in _ALT_COLUMNS:
        col = _ALT_COLUMNS[col]
    else:
        col = col[0:4].strip()
    return col


def get_header(cols=_DEFAULT_COLUMN_ORDER):
    """Return a row of header strings for the provided cols."""

    return (_EVENT_COLUMNS[colkey(c)] for c in cols)


def sub_depend(depend, oldevno, newevno):
    """Alter any instance of oldevno in depend to newevno"""
    alter = False
    nv = []
    for dep in depend.split():
        evno = dep.strip()
        if evno == oldevno:
            evno = newevno
            alter = True
        nv.append(evno)
    if alter:
        depend = ' '.join(nv)
    return depend


def sub_autospec(autospec, oldevno, newevno):
    """Alter any instance of oldevno in autospec to newevno"""
    alter = False
    nv = []
    for spec in autospec.split(';'):
        if ':' in spec:
            evno, rule = spec.split(':', 1)
            evno = evno.strip()
            rule = rule.strip()
            if evno == oldevno:
                evno = newevno
                alter = True
            nv.append(':'.join((evno, rule)))
    if alter:
        autospec = '; '.join(nv)
    return autospec


class event:
    """CSV-backed event listing."""

    def copy(self):
        """Return copy of this event with a blank ID"""
        nev = event(evid=None)
        for k, v in self._store.items():
            if k != 'evid':
                nev._store[k] = v
        nev._notify = self._notify
        return nev

    def update_autospec(self, oldevno, newevno):
        newspec = sub_autospec(self['auto'], oldevno, newevno)
        if newspec != self['auto']:
            self.set_value('auto', newspec)

    def update_depend(self, oldevno, newevno):
        newdepend = sub_depend(self['depend'], oldevno, newevno)
        if newdepend != self['depend']:
            self.set_value('depend', newdepend)

    def get_row(self, coldump=_DEFAULT_COLUMN_ORDER):
        """Return a row ready to export."""
        return (str(self[c]) for c in coldump)

    def get_info(self, showevno=False):
        """Return a concatenated and stripped event information string."""
        rv = []
        if showevno and self['type'] != 'break':
            rv.append('Event\u2006' + self.get_evno())
        if self['pref']:
            rv.append(self['pref'])
        if self['info']:
            rv.append(self['info'])
        return ' '.join(rv)

    def get_type(self):
        """Return event type string."""
        ret = self['type']
        if ret in _EVENT_TYPES:
            ret = _EVENT_TYPES[ret]
        return ret

    def get_evno(self):
        """Return preferred display event number."""
        evno = self['evid']
        ov = self['evov']
        if ov:
            evno = ov
        return evno

    def set_notify(self, callback=None):
        """Set or clear the notify callback for the event."""
        if callback is not None:
            self._notify = callback
        else:
            self._notify = self._def_notify

    def get_value(self, key):
        """Alternate value fetch."""
        return self.__getitem__(key)

    def set_value(self, key, value):
        """Update a value without triggering notify."""
        key = colkey(key)
        self._store[key] = value

    def notify(self):
        """Forced notify."""
        self._notify(self._store['evid'])

    def __init__(self, evid=None, notify=None, cols={}):
        self._store = dict(cols)
        self._notify = self._def_notify
        if 'evid' not in self._store:
            self._store['evid'] = evid
        if notify is not None:
            self._notify = notify

    def _def_notify(self, data=None):
        pass

    def __getitem__(self, key):
        key = colkey(key)
        if key in self._store:
            return self._store[key]
        elif key in _EVENT_DEFAULTS:
            return _EVENT_DEFAULTS[key]
        else:
            return ''

    def __setitem__(self, key, value):
        key = colkey(key)
        self._store[key] = value
        self._notify(self._store['evid'])

    def __delitem__(self, key):
        key = colkey(key)
        del (self._store[key])
        self._notify(self._store['evid'])

    def __contains__(self, key):
        key = colkey(key)
        return key in self._store


class eventdb:
    """Event database."""

    def add_empty(self, evno=None, notify=True):
        """Add a new empty row to the event model."""
        if evno is None:
            evno = self.nextevno()
        ev = event(evid=evno, notify=self._notify)
        self._store[evno] = ev
        self._index.append(evno)
        if notify:
            self._notify(None)
        _log.debug('Added empty event %r', evno)
        return ev

    def clear(self):
        """Clear event model."""
        self._index.clear()
        self._store.clear()
        self._notify(None)
        _log.debug('Event model cleared')

    def change_evno(self, oldevno, newevno, notify=True):
        """Alter an event id."""
        if oldevno not in self:
            _log.error('Change event %r not found', oldevno)
            return False

        if newevno in self:
            _log.error('New event %r already exists', newevno)
            return False

        oktochg = True
        if self._evno_change_cb is not None:
            oktochg = self._evno_change_cb(oldevno, newevno)
        if oktochg:
            ref = self._store[oldevno]
            ref.set_value('evid', newevno)  # may already be set
            idx = self._index.index(oldevno)
            self._store[newevno] = ref
            self._index[idx] = newevno
            del self._store[oldevno]
            _log.debug('Updated event %r to %r', oldevno, newevno)
            if notify:
                self._notify(None)
            return True
        return False

    def add_event(self, newevent):
        """Append newevent to model."""
        eid = newevent['evid']
        if eid is None:
            eid = self.nextevno()
        elif not isinstance(eid, str):
            _log.debug('Converted %r to event id: %r', eid, str(eid))
            eid = str(eid)
        evno = eid
        if evno in self._index:
            baseno = evno.rsplit('.', 1)[0]
            count = 0
            while evno in self._index:
                count += 1
                evno = '%s.%d' % (
                    baseno,
                    count,
                )
            _log.info('Duplicate evid %r changed to %r', eid, evno)
        newevent.set_value('evid', evno)
        newevent.set_notify(self._notify)
        self._store[evno] = newevent
        self._index.append(evno)

    def _loadrow(self, r, colspec):
        nev = event()
        for i in range(0, len(colspec)):
            if len(r) > i:  # column data in row
                val = r[i].translate(strops.PRINT_UTRANS)
                key = colspec[i]
                if key in _EVENT_COLUMN_CONVERTERS:
                    val = _EVENT_COLUMN_CONVERTERS[key](val)
                nev.set_value(key, val)  # don't notify
        if not nev['evid']:
            evno = self.nextevno()
            _log.info('Event without id assigned %r', evno)
            nev.set_value('evid', evno)
        self.add_event(nev)

    def load(self, csvfile=None):
        """Load events from supplied CSV file."""
        if not os.path.isfile(csvfile):
            _log.debug('Events file %r not found', csvfile)
            return
        _log.debug('Loading from %r', csvfile)
        with open(csvfile, encoding='utf-8', errors='replace') as f:
            cr = csv.reader(f)
            incols = None  # no header
            for r in cr:
                if len(r) > 0:  # got a data row
                    if incols is not None:  # already got col header
                        self._loadrow(r, incols)
                    else:
                        # determine input column structure
                        if colkey(r[0]) in _EVENT_COLUMNS:
                            incols = []
                            for col in r:
                                incols.append(colkey(col))
                        else:
                            incols = _DEFAULT_COLUMN_ORDER  # assume full
                            self._loadrow(r, incols)
        self._notify(None)

    def save(self, csvfile=None):
        """Save current model content to CSV file."""
        if len(self._index) != len(self._store):
            _log.error('Index out of sync with model, rebuilding')
            self._index = [a for a in self._store]

        _log.debug('Saving events to %r', csvfile)
        with metarace.savefile(csvfile) as f:
            cr = csv.writer(f, quoting=csv.QUOTE_ALL)
            cr.writerow(get_header(self.include_cols))
            # Output events in indexed order
            for evno in self._index:
                ev = self._store[evno]
                cr.writerow(ev.get_row())

    def nextevno(self):
        """Try and return a new event number string."""
        lmax = 1
        for r in self._index:
            if r.isdigit() and int(r) >= lmax:
                lmax = int(r) + 1
        return str(lmax)

    def set_evno_change_cb(self, cb, data=None):
        """Set the event no change callback."""
        self._evno_change_cb = cb

    def index(self, evno):
        """Return index of event no"""
        return self._index.index(evno)

    def getfirst(self):
        """Return the first event in the db."""
        ret = None
        if len(self._index) > 0:
            ret = self[self._index[0]]
        return ret

    def getnextrow(self, ref, scroll=True):
        """Return reference to the row one after current selection."""
        ret = None
        if ref is not None:
            path = self._index.index(ref['evid']) + 1
            if path >= 0 and path < len(self._index):
                ret = self[self._index[path]]  # check reference
        return ret

    def getprevrow(self, ref, scroll=True):
        """Return reference to the row one after current selection."""
        ret = None
        if ref is not None:
            path = self._index.index(ref['evid']) - 1
            if path >= 0 and path < len(self._index):
                ret = self[self._index[path]]  # check reference
        return ret

    def reindex(self, newindex):
        """Re-order index, and notify"""
        viewevs = set()
        self._index.clear()
        for evno in newindex:
            if evno in self._store:
                self._index.append(evno)
                viewevs.add(evno)
            else:
                _log.warning('Ignore invalid event id from view: %r', evno)
        for evno in self._store:
            if evno not in viewevs:
                _log.debug('Appending orphaned event to index: %r', evno)
                self._index.append(evno)
        if len(self._index) != len(self._store):
            _log.error('Event index corrupt, reload required')

    def __len__(self):
        return len(self._store)

    def __delitem__(self, key):
        self._index.remove(key)
        del self._store[key]

    def __iter__(self):
        for evno in self._index:
            yield (self._store[evno])

    def __getitem__(self, key):
        return self._store[key]

    def __setitem__(self, key, value):
        self.__store[key] = value

    def __contains__(self, key):
        return key in self._store

    def values(self):
        return self._store.values()

    def keys(self):
        return self._store.keys()

    def items(self):
        return self._store.items()

    def set_notify(self, cb=None):
        """Set the data change notification callback."""
        if cb is None:
            cb = self._defnotify
        self._notify = cb
        for ev in self._store.values():
            ev.set_notify(cb)

    def _def_notify(self, data=None):
        """Handle changes in db."""
        pass

    def __init__(self, racetypes=None):
        """Constructor for the event db."""
        self._index = []
        self._store = {}

        self._notify = self._def_notify
        self._evno_change_cb = None

        self.include_cols = _DEFAULT_COLUMN_ORDER
        if racetypes is not None:
            self.racetypes = racetypes
        else:
            self.racetypes = _EVENT_TYPES
