# SPDX-License-Identifier: MIT
"""Classification/Medal meta-event handler for trackmeet."""

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

_log = logging.getLogger('classification')
_log.setLevel(logging.DEBUG)

# config version string
EVENT_ID = 'classification-2.1'

# Model columns
COL_NO = 0
COL_NAME = 1
COL_CAT = 4
COL_PLACE = 5
COL_MEDAL = 6

# scb function key mappings
key_reannounce = 'F4'  # (+CTRL)
key_abort = 'F5'  # (+CTRL)
key_startlist = 'F3'
key_results = 'F4'


class classification:

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

    def standingstr(self, width=None):
        """Return an event status string for reports and scb."""
        return self._standingstat

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
                'medals': ''
            }
        })
        cr.add_section('event')
        if not cr.load(self.configfile):
            _log.info('%r not read, loading defaults', self.configfile)

        if self.event['info'] == 'Omnium':
            # pre-load source events by searching event db unless config'd
            if not cr.get('event', 'placesrc'):
                cr.set('event', 'showcats', True)
                cr.set('event', 'medals', 'Gold Silver Bronze')
                sources = {
                    'Scratch': None,
                    'Tempo': None,
                    'Elimination': None,
                    'Points': None
                }
                mycat = self.event['prefix']
                for e in self.meet.edb:
                    if e['prefix'] == mycat and e['info'] in sources:
                        sources[e['info']] = e['evid']
                        _log.debug('Found event %s for %s', e['evid'],
                                   e['info'])
                if sources['Points'] is not None:
                    _log.debug('Using event %s for classification places',
                               sources['Points'])
                    cr.set('event', 'placesrc',
                           '%s:1-24' % (sources['Points'], ))
                showevts = []
                revevt = {}
                for sid in ('Scratch', 'Tempo', 'Elimination', 'Points'):
                    if sources[sid] is not None:
                        showevts.append(sources[sid])
                        revevt[sources[sid]] = sid
                if showevts:
                    _log.debug('Using %r as show events list', showevts)
                    evtlist = ' '.join(showevts)
                    cr.set('event', 'showevents', evtlist)
                    self.event['depends'] = evtlist
                    for sid in showevts:
                        try:
                            # while here - visit event config
                            # and update omnium flag
                            ev = self.meet.edb[sid]
                            config = self.meet.event_configfile(sid)
                            ecr = jsonconfig.config()
                            ecr.add_section('event')
                            ecr.load(config)
                            ecr.set('event', 'inomnium', True)
                            ecr.set('event', 'showcats', True)
                            stype = revevt[sid]
                            if stype == 'Points':
                                startevid = sources['Scratch']
                                if startevid is not None:
                                    ev.set_value('starters',
                                                 '%s:1-24' % (startevid, ))
                            elif stype in ('Tempo', 'Elimination'):
                                startevid = sources['Points']
                                if startevid is not None:
                                    ev.set_value('starters',
                                                 '%s:1-24' % (startevid, ))
                            _log.debug('Saving event %s config file %s', sid,
                                       config)
                            with metarace.savefile(config) as f:
                                ecr.write(f)
                        except Exception as e:
                            _log.error('%s updating config: %s',
                                       e.__class__.__name__, e)
                cr.set('event', 'showinfo', False)
            else:
                _log.debug('Omnium already configured')

        self.showcats = cr.get_bool('event', 'showcats')
        self.showevents = cr.get('event', 'showevents')
        self.placesrc = cr.get('event', 'placesrc')
        self.medals = cr.get('event', 'medals')
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

    def startlist_report(self, program=False):
        """Return a startlist report."""
        ret = []
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)
        sec.nobreak = True
        headvec = [
            'Event', self.evno, ':', self.event['pref'], self.event['info']
        ]
        if not program:
            headvec.append('- Start List')
        sec.heading = ' '.join(headvec)
        lapstring = strops.lapstring(self.event['laps'])
        substr = ' '.join(
            (lapstring, self.event['distance'], self.event['phase'])).strip()
        if substr:
            sec.subheading = substr
        sec.lines = []
        for r in self.riders:
            rno = r[COL_NO]
            if 't' in self.series:  # Team no hack
                rno = ' '  # force name
            rh = self.meet.rdb.get_rider(rno, self.series)
            rname = ''
            if rh is not None:
                rname = rh.resname()
            sec.lines.append([None, rno, rname, None, None, None])
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
        cw.set('event', 'showevents', self.showevents)
        cw.set('event', 'placesrc', self.placesrc)
        cw.set('event', 'medals', self.medals)
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

    def result_gen(self):
        """Generator function to export a final result."""
        for r in self.riders:
            bib = r[COL_NO]
            rank = None
            info = ''
            rks = r[COL_PLACE]
            if rks:
                if rks.isdigit():
                    rank = int(rks)
                    info = r[COL_MEDAL]
                else:
                    # TODO: allow for 'dnf'/'dns' here, propagates into event
                    rank = rks
                    info = None  # no seeding info available
            time = None

            yield (bib, rank, time, info)

    def result_report(self, recurse=True):  # by default include inners
        """Return a list of report sections containing the race result."""
        ret = []

        # start with the overall result
        secid = 'ev-' + str(self.evno).translate(strops.WEBFILE_UTRANS)
        sec = report.section(secid)
        sec.nobreak = True
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

        prevmedal = ''
        sec.lines = []
        for r in self.riders:
            rno = r[COL_NO]
            rh = self.meet.rdb.get_rider(rno, self.series)
            rname = ''
            plink = ''
            rcat = ''
            if 't' in self.series:  # Team no hack
                rno = ' '  # force name
                if rh is not None:
                    rname = rh['first']
            else:
                if rh is not None:
                    rname = rh.resname()
                    if rh['uciid']:
                        rcat = rh['uciid']  # overwrite by force

                    # overwrite info if showcats true
                    if self.showcats:
                        rcat = rh.primary_cat()

                    # consider partners here
                    if rh['cat'] and 'tandem' in rh['cat'].lower():
                        ph = self.meet.rdb.get_rider(rh['note'], self.series)
                        if ph is not None:
                            plink = [
                                '', '',
                                ph.resname() + ' - Pilot', ph['uciid'], '', '',
                                ''
                            ]

            rank = ''
            rks = r[COL_PLACE]
            if rks:
                rank = rks
                if rank.isdigit():
                    rank += '.'

            medal = ''
            mds = r[COL_MEDAL]
            if mds:
                medal = mds
            if medal == '' and prevmedal != '':
                # add empty line
                sec.lines.append([None, None, None])
            prevmedal = medal

            nrow = [rank, rno, rname, rcat, None, medal, plink]
            sec.lines.append(nrow)
            if 't' in self.series:
                for trno in strops.riderlist_split(rh['note']):
                    trh = self.meet.rdb.get_rider(trno, self.series)
                    if trh is not None:
                        trname = trh.resname()
                        trinf = trh['uciid']
                        sec.lines.append(
                            [None, trno, trname, trinf, None, None, None])
        ret.append(sec)

        if len(self.decisions) > 0:
            ret.append(self.meet.decision_section(self.decisions))

        if recurse:
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

    def changerider(self, oldNo, newNo):
        """Update rider no in event"""
        # classification riders are automatic only
        return false

    def addrider(self, bib='', place=''):
        """Add specified rider to race model."""
        bib = bib.upper()
        nr = [bib, '', '', '', '', '', '']
        er = self._getrider(bib)
        if not bib or er is None:
            dbr = self.meet.rdb.get_rider(bib, self.series)
            if dbr is not None:
                nr[COL_NAME] = dbr.listname()
                nr[COL_CAT] = dbr['cat']
            nr[COL_PLACE] = place
            return self.riders.append(nr)
        else:
            _log.warning('Rider %r already in event %s', bib, self.evno)
            return None

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
        """Remove the specified rider from the model."""
        i = self._getiter(bib)
        if i is not None:
            self.riders.remove(i)

    def recalculate(self):
        """Update internal model."""
        self.riders.clear()

        # Create ordered place lookup
        currank = 0
        lookup = {}
        for p in self.placesrc.split(';'):
            placegroup = p.strip()
            if placegroup:
                #_log.debug('Adding place group %r at rank %r', placegroup,
                #currank)
                if placegroup == 'X':
                    _log.debug('Added placeholder at rank %r', currank)
                    currank += 1
                else:
                    specvec = placegroup.split(':')
                    if len(specvec) == 2:
                        evno = specvec[0].strip()
                        if evno not in lookup:
                            lookup[evno] = {}
                        if evno != self.evno:
                            placeset = strops.placeset(specvec[1])
                            for i in placeset:
                                lookup[evno][i] = currank
                                currank += 1
                        else:
                            _log.warning('Ignored ref to self %r at rank %r',
                                         placegroup, currank)
                    else:
                        _log.warning('Invalid placegroup %r at rank %r',
                                     placegroup, currank)
            else:
                _log.debug('Empty placegroup at rank %r', currank)

        # Create an ordered list of rider numbers using lookup
        placemap = {}
        maxcrank = 0
        self.finished = True  # Assume finished unless one source is not
        for evno in lookup:
            r = self.meet.get_event(evno, False)
            if r is None:
                _log.warning('Event %r not found for lookup %r', evno,
                             lookup[evno])
                return
            r.loadconfig()  # now have queryable event handle
            if r.finished:
                for res in r.result_gen():
                    if isinstance(res[1], int):
                        if res[1] in lookup[evno]:
                            crank = lookup[evno][res[1]] + 1
                            maxcrank = max(maxcrank, crank)
                            #_log.debug(
                            #'Assigned place %r to rider %r at rank %r',
                            #crank, res[0], res[1])
                            if crank not in placemap:
                                placemap[crank] = []
                            placemap[crank].append(res[0])
            else:
                self.finished = False
            r = None

        # Add riders to model in rank order
        i = 1
        while i <= maxcrank:
            if i in placemap:
                for r in placemap[i]:
                    self.addrider(r, str(i))
            i += 1

        if len(self.riders) > 0:  # got at least one result to report
            self.onestart = True

        # Mark medals/awards if required and determine status
        self._standingstat = ''
        medalmap = {}
        placecount = 0
        medalcount = 0
        mplace = 1
        for m in self.medals.split():
            medalmap[mplace] = m
            mplace += 1
        mtotal = len(medalmap)
        for r in self.riders:
            rks = r[COL_PLACE]
            if rks.isdigit():
                rank = int(rks)
                placecount += 1
                if rank in medalmap:
                    r[COL_MEDAL] = medalmap[rank]
                    medalcount += 1
        if placecount > 0:
            if medalcount == mtotal:
                self._standingstat = 'Result'
            elif medalcount > 0:
                self._standingstat = 'Provisional Result'
            else:
                self._standingstat = 'Virtual Standing'
        return

    def key_event(self, widget, event):
        """Race window key press handler."""
        if event.type == Gdk.EventType.KEY_PRESS:
            key = Gdk.keyval_name(event.keyval) or 'None'
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                if key == key_abort or key == key_reannounce:
                    # override ctrl+f5
                    self.recalculate()
                    GLib.idle_add(self.delayed_announce)
                    return True
            elif key[0] == 'F':
                if key == key_startlist:
                    self.do_startlist()
                    GLib.idle_add(self.delayed_announce)
                    return True
                elif key == key_results:
                    self.do_places()
                    GLib.idle_add(self.delayed_announce)
                    return True
        return False

    def delayed_announce(self):
        """Initialise the announcer's screen after a delay."""
        ## TODO because # riders often exceeds 24 - requires paging
        if self.winopen:
            # clear page
            self.meet.txt_clear()
            self.meet.txt_title(self.event.get_info(showevno=True))
            self.meet.txt_line(1)
            self.meet.txt_line(19)

            # write out riders
            lmedal = ''
            posoft = 0
            l = 4
            for r in self.riders:
                if l > 17:
                    l = 4
                    posoft += 41
                plstr = ''
                pls = r[COL_PLACE]
                if pls:
                    plstr = pls
                    if plstr.isdigit():
                        plstr += '.'
                plstr = strops.truncpad(plstr, 3, 'l')
                bibstr = strops.truncpad(r[COL_NO], 3, 'r')
                namestr = strops.truncpad(r[COL_NAME], 25)
                medal = r[COL_MEDAL]
                if lmedal != '' and medal == '':
                    l += 1  # gap to medals
                lmedal = medal
                ol = [plstr, bibstr, namestr, medal]
                self.meet.txt_postxt(l, posoft,
                                     ' '.join([plstr, bibstr, namestr, medal]))
                l += 1

        return False

    def do_startlist(self):
        """Show result on scoreboard."""
        return self.do_places()

    def _getname(self, bib, width=32):
        """Return a name and club for the rider if known"""
        name = ''
        club = ''
        dbr = self.meet.rdb.get_rider(bib, self.series)
        if dbr is not None:
            name = dbr.fitname(width)
            club = dbr['organisation']
        return name, club

    def do_places(self):
        """Show race result on scoreboard."""
        # Draw a 'medal ceremony' on the screen
        resvec = []
        count = 0
        teamnames = False
        name_w = self.meet.scb.linelen - 12
        fmt = ((3, 'l'), (3, 'r'), ' ', (name_w, 'l'), (5, 'r'))
        if self.series and self.series[0].lower() == 't':
            teamnames = True
            name_w = self.meet.scb.linelen - 9
            fmt = ((3, 'l'), ' ', (name_w, 'l'), (5, 'r'))

        for r in self.riders:
            plstr = r[COL_PLACE]
            if plstr.isdigit():
                plstr = plstr + '.'
            no = r[COL_NO]
            name, club = self._getname(no, name_w)
            if len(club) != 3:
                club = ''
            if not teamnames:
                resvec.append((plstr, no, name, club))
            else:
                resvec.append((plstr, name, club))
            count += 1
        self.meet.scbwin = None
        header = self.meet.racenamecat(self.event)
        ## TODO: Flag Provisional
        evtstatus = 'Final Classification'.upper()
        self.meet.scbwin = scbwin.scbtable(scb=self.meet.scb,
                                           head=self.meet.racenamecat(
                                               self.event),
                                           subhead=evtstatus,
                                           coldesc=fmt,
                                           rows=resvec)
        self.meet.scbwin.reset()
        return False

    def recover_start(self):
        """Recover missed start time"""
        pass

    def timercb(self, e):
        """Handle a timer event."""
        return False

    def timeout(self):
        """Update scoreboard and respond to timing events."""
        if not self.winopen:
            return False
        return True

    def do_properties(self):
        """Run race properties dialog."""
        b = uiutil.builder('classification_properties.ui')
        dlg = b.get_object('properties')
        dlg.set_transient_for(self.meet.window)
        se = b.get_object('race_series_entry')
        se.set_text(self.series)
        ee = b.get_object('race_showevents_entry')
        ee.set_text(self.showevents)
        pe = b.get_object('race_placesrc_entry')
        pe.set_text(self.placesrc)
        me = b.get_object('race_medals_entry')
        me.set_text(self.medals)
        response = dlg.run()
        if response == 1:  # id 1 set in glade for "Apply"
            _log.debug('Updating event properties')
            self.placesrc = pe.get_text()
            self.medals = me.get_text()
            self.showevents = ee.get_text()

            # update series
            ns = se.get_text()
            if ns != self.series:
                self.series = ns
                self.event['seri'] = ns

            self.recalculate()
            GLib.idle_add(self.delayed_announce)
        else:
            _log.debug('Edit event properties cancelled')

        # if prefix is empty, grab input focus
        if not self.prefix_ent.get_text():
            self.prefix_ent.grab_focus()
        dlg.destroy()

    def show(self):
        """Show race window."""
        self.frame.show()

    def hide(self):
        """Hide race window."""
        self.frame.hide()

    def update_expander_lbl_cb(self):
        """Update race info expander label."""
        self.info_expand.set_label(self.meet.infoline(self.event))

    def editent_cb(self, entry, col):
        """Shared event entry update callback."""
        if col == 'pref':
            self.event['pref'] = entry.get_text()
        elif col == 'info':
            self.event['info'] = entry.get_text()

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

    def __init__(self, meet, event, ui=True):
        """Constructor."""
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
        self.placesrc = ''
        self.medals = ''
        self.decisions = []
        self.finished = False
        self._standingstat = ''
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
            uiutil.mkviewcoltxt(t, 'Medal', COL_MEDAL)
            t.show()
            b.get_object('classification_result_win').add(t)
            b.connect_signals(self)
