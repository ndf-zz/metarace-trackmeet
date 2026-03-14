# SPDX-License-Identifier: MIT
"""Gtk user interface helper functions"""

import os
import sys
import gi
import logging
import json
import threading
from math import floor, ceil
from importlib.resources import files
from contextlib import suppress
from subprocess import run

gi.require_version("GLib", "2.0")
from gi.repository import GLib

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

gi.require_version('Pango', '1.0')
from gi.repository import Pango

import metarace
from metarace import tod
from metarace import strops
from metarace.jsonconfig import config
from metarace.riderdb import rider
from metarace.standards import Factors, CategoryInfo
from .eventdb import Event

_log = logging.getLogger('uiutil')
_log.setLevel(logging.DEBUG)

# Resources package
RESOURCE_PKG = 'trackmeet.ui'

# Allowed automatic update packages
_ALLOWED_UPDATES = (
    'metarace-trackmeet',
    'metarace-roadmeet',
    'metarace-tagreg',
    'metarace-ttstart',
    'metarace',
)
_UPDATE_PROC = {
    'check': {
        'thread': None,
        'lock': threading.Lock()
    },
    'run': {
        'thread': None,
        'lock': threading.Lock()
    },
    'standards': {
        'thread': None,
        'lock': threading.Lock()
    },
}

# competition ID labels
_COMPIDS = {
    'scratch race': 'scratch',
    'elimination race': 'elimination',
    'points race': 'points',
    'tempo race': 'tempo',
}

# competition abbreviations
_COMPABBREVS = {
    'pursuit': 'ip',
    'individualpursuit': 'ip',
    'teampursuit': 'tp',
    'teamsprint': 'ts',
    'timetrial': 'tt',
    'scratch': 'sc',
    'scratchrace': 'sc',
    'elimination': 'e',
    'eliminationrace': 'e',
    'points': 'p',
    'pointsrace': 'p',
    'keirin': 'k',
    'sprint': 'sp',
    'madison': 'm',
    '': '',
}

# standard sprint competition phases

# Olympic Sprint - Repechages and grouped others placed by 200 TT
_OLY_SPRINT_COMPETITION = {
    '1.32a': {  # AU specific - skip 1st repechage
        'evid': 'r32',
        'source': {
            'qualifying': '1-32',
        },
        'entrants': 32,
        'label': '1/32 Final',
        'qualifiers': 16,
        'heats': 1,
        'next': '1.16',
        'rule': 'Winners to 1/16 final',
        'places': None,
        'others': '17-32',
        'otherstime': False,
        'firstround': True,
    },
    '1.32': {
        'evid': 'r24',
        'source': {
            'qualifying': '1-24',
        },
        'entrants': 24,
        'label': '1/32 Final',
        'qualifiers': 12,
        'heats': 1,
        'next': 'rep189',
        'rule': 'Winners to 1/16 final; Others to repechage',
        'places': None,
        'others': None,
        'otherstime': False,
        'firstround': True,
    },
    'rep189': {
        'evid': 'rep189',
        'source': {
            '1.32': '24,17,16',
        },
        'entrants': 3,
        'label': 'Repechage 1v8v9',
        'qualifiers': 1,
        'heats': 0,
        'next': 'rep2710',
        'rule': 'Winner to 1/16 final',
        'places': None,
        'others': '2,3',
        'otherstime': False,
        'firstround': False,
    },
    'rep2710': {
        'evid': 'rep2710',
        'source': {
            '1.32': '23,18,15',
        },
        'entrants': 3,
        'label': 'Repechage 2v7v12',
        'qualifiers': 1,
        'heats': 0,
        'next': 'rep3611',
        'rule': 'Winner to 1/16 final',
        'places': None,
        'others': '2,3',
        'otherstime': False,
        'firstround': False,
    },
    'rep3611': {
        'evid': 'rep3611',
        'source': {
            '1.32': '22,19,14',
        },
        'entrants': 3,
        'label': 'Repechage 3v6v11',
        'qualifiers': 1,
        'heats': 0,
        'next': 'rep4512',
        'rule': 'Winner to 1/16 final',
        'places': None,
        'others': '2,3',
        'otherstime': False,
        'firstround': False,
    },
    'rep4512': {
        'evid': 'rep4512',
        'source': {
            '1.32': '21,20,13',
        },
        'entrants': 3,
        'label': 'Repechage 4v5v12',
        'qualifiers': 1,
        'heats': 0,
        'next': '1.16',
        'rule': 'Winner to 1/16 final',
        'places': None,
        'others': '2,3',
        'otherstime': False,
        'firstround': False,
    },
    '1.16': {
        'evid': 'r16',
        'source': {
            '1.32a': '1-16',
            '1.32': '1-12',
            'rep189': '1',
            'rep2710': '1',
            'rep3611': '1',
            'rep4512': '1',
        },
        'entrants': 16,
        'label': '1/16 Final',
        'qualifiers': 8,
        'heats': 1,
        'next': 'rep8',
        'rule': 'Winners to 1/8 final; Others to repechage',
        'places': None,
        'others': None,
        'otherstime': False,
        'firstround': True,
    },
    'rep8': {
        'evid': 'rep8',
        'source': {
          '1.16': '16,15,14,13,12,11,10,9',
        },
        'entrants': 8,
        'label': 'Repechage',
        'qualifiers': 4,
        'heats': 1,
        'next': '1.8',
        'rule': 'Winners to 1/8 final',
        'places': None,
        'others': '5-8',
        'otherstime': False,
        'firstround': False,
    },
    '1.8': {
        'evid': 'r12',
        'source': {
            '1.16': '1-8',
            'rep8': '1-4',
        },
        'entrants': 12,
        'label': '1/8 Final',
        'qualifiers': 6,
        'heats': 1,
        'next': 'rep145',
        'rule': 'Winners to 1/4 final; Others to repechage',
        'places': None,
        'others': None,
        'otherstime': False,
        'firstround': True,
    },
    'rep145': {
        'evid': 'rep145',
        'source': {
            '1.8': '12,9,8',
        },
        'entrants': 3,
        'label': 'Repechage 8v9v12',
        'qualifiers': 1,
        'heats': 0,
        'next': 'rep236',
        'rule': 'Winner to 1/4 final',
        'places': None,
        'others': '2,3',
        'otherstime': False,
        'firstround': False,
    },
    'rep236': {
        'evid': 'rep236',
        'source': {
            '1.8': '11,10,7',
        },
        'entrants': 3,
        'label': 'Repechage 7v10v11',
        'qualifiers': 1,
        'heats': 0,
        'next': '1.4',
        'rule': 'Winner to 1/4 final',
        'places': None,
        'others': '2,3',
        'otherstime': False,
        'firstround': False,
    },
    '1.4': {
        'evid': 'r8',
        'source': {
            '1.8': '1-6',
            'rep145': '1',
            'rep236': '1',
        },
        'entrants': 8,
        'label': '1/4 Final',
        'qualifiers': 4,
        'heats': 3,
        'next': '5-8',
        'rule': 'Winners to 1/2 final, Others to 5-8 final',
        'places': None,
        'others': None,
        'otherstime': False,
        'firstround': True,
    },
    '5-8': {
        'evid': '5-8',
        'source': {
            '1.4': '5-8',
        },
        'entrants': 4,
        'label': '5-8 Final',
        'qualifiers': None,
        'heats': 0,  # derby
        'next': '1.2',
        'rule': 'For places 5 to 8',
        'places': '1-4',
        'others': None,
        'otherstime': False,
        'firstround': False,
    },
    '1.2': {
        'evid': 'r4',
        'source': {
            '1.4': '1-4',
        },
        'entrants': 4,
        'label': '1/2 Final',
        'qualifiers': 4,
        'heats': 3,
        'next': 'final',
        'rule': 'Winners to gold final; Others to bronze',
        'places': None,
        'others': None,
        'otherstime': False,
        'firstround': True,
    },
    'final': {
        'evid': 'f',
        'source': {
            '1.2': '3,1,2,4',
        },
        'entrants': 4,
        'label': 'Final',
        'qualifiers': None,
        'heats': 3,
        'next': None,
        'rule': '',
        'places': '2,3,1,4',
        'others': None,
        'otherstime': False,
        'firstround': True,
    },
}

# Worlds sprint - no repechage, others placed n-m in-phase by 200m TT
_SPRINT_COMPETITION = {
    '1.16': {
        'evid': 'r28',
        'source': {
            'qualifying': '1-28',
        },
        'entrants': 28,
        'label': '1/16 Final',
        'qualifiers': 16,
        'heats': 1,
        'next': '1.8',
        'rule': 'Winners to 1/8 final',
        'places': '17-28',
        'others': None,
        'otherstime': True,
        'firstround': True,
    },
    '1.8': {
        'evid': 'r16',
        'source': {
            '1.16': '1-16',
        },
        'entrants': 16,
        'label': '1/8 Final',
        'qualifiers': 8,
        'heats': 1,
        'next': '1.4',
        'rule': 'Winners to 1/4 final',
        'places': '9-16',
        'others': None,
        'otherstime': True,
        'firstround': True,
    },
    '1.4': {
        'evid': 'r8',
        'source': {
            '1.8': '1-8',
        },
        'entrants': 8,
        'label': '1/4 Final',
        'qualifiers': 4,
        'heats': 3,
        'next': '1.2',
        'rule': 'Winners to 1/2 final',
        'places': '5-8',
        'others': None,
        'otherstime': True,
        'firstround': True,
    },
    '1.2': {
        'evid': 'r4',
        'source': {
            '1.4': '1-4',
        },
        'entrants': 4,
        'label': '1/2 Final',
        'qualifiers': 4,
        'heats': 3,
        'next': 'final',
        'rule': 'Winners to gold final; Others to bronze',
        'places': None,
        'others': None,
        'otherstime': False,
        'firstround': True,
    },
    'final': {
        'evid': 'f',
        'source': {
            '1.2': '3,1,2,4',
        },
        'entrants': 4,
        'label': 'Final',
        'qualifiers': None,
        'heats': 3,
        'next': None,
        'rule': '',
        'places': '2,3,1,4',
        'others': None,
        'otherstime': False,
        'firstround': True,
    },
}

# Points Race Fallback Values [3.2.117]
# laplen => cat => Q/F => (dist, laps. sprints)
# Note: laplen is truncated to int
_POINTS_RACES_T1 = {
    166: {
        'ME': {
            'Q': (15000, 90, 9),
            'F': (30000, 180, 18),
        },
        'WE': {
            'Q': (10000, 60, 6),
            'F': (20000, 120, 12),
        },
        'MJ': {
            'Q': (10000, 60, 6),
            'F': (20000, 120, 12),
        },
        'WJ': {
            'Q': (10000, 60, 6),
            'F': (15000, 90, 9),
        },
    },
    200: {
        'ME': {
            'Q': (14000, 70, 7),
            'F': (30000, 150, 15),
        },
        'WE': {
            'Q': (10000, 50, 5),
            'F': (20000, 100, 10),
        },
        'MJ': {
            'Q': (10000, 50, 5),
            'F': (20000, 100, 10),
        },
        'WJ': {
            'Q': (8000, 40, 4),
            'F': (16000, 80, 8),
        },
    },
    250: {
        'ME': {
            'Q': (15000, 60, 6),
            'F': (30000, 150, 15),
        },
        'WE': {
            'Q': (10000, 40, 4),
            'F': (20000, 80, 8),
        },
        'MJ': {
            'Q': (10000, 40, 4),
            'F': (20000, 80, 8),
        },
        'WJ': {
            'Q': (10000, 40, 4),
            'F': (15000, 60, 6),
        },
    },
    285: {
        'ME': {
            'Q': (16000, 56, 5),
            'F': (30000, 105, 10),
        },
        'WE': {
            'Q': (12000, 42, 4),
            'F': (20000, 70, 7),
        },
        'MJ': {
            'Q': (12000, 42, 4),
            'F': (20000, 70, 7),
        },
        'WJ': {
            'Q': (10000, 35, 3),
            'F': (16000, 56, 5),
        },
    },
    333: {
        'ME': {
            'Q': (14000, 42, 8),
            'F': (30000, 90, 18),
        },
        'WE': {
            'Q': (10000, 30, 6),
            'F': (20000, 60, 12),
        },
        'MJ': {
            'Q': (10000, 30, 6),
            'F': (20000, 60, 12),
        },
        'WJ': {
            'Q': (10000, 30, 6),
            'F': (16000, 48, 9),
        },
    },
    400: {
        'ME': {
            'Q': (14000, 35, 7),
            'F': (30000, 75, 15),
        },
        'WE': {
            'Q': (10000, 25, 5),
            'F': (20000, 50, 10),
        },
        'MJ': {
            'Q': (10000, 25, 5),
            'F': (20000, 50, 10),
        },
        'WJ': {
            'Q': (8000, 20, 4),
            'F': (16000, 40, 8),
        },
    },
}
_POINTS_RACES_T2 = {
    200: {
        'ME': {
            'Q': (20000, 100, 10),
            'F': (40000, 200, 20),
        },
        'WE': {
            'Q': (15000, 75, 7),
            'F': (25000, 125, 12),
        },
        'MJ': {
            'Q': (15000, 75, 7),
            'F': (25000, 125, 12),
        },
        'WJ': {
            'Q': (10000, 50, 5),
            'F': (20000, 100, 10),
        },
    },
    250: {
        'ME': {
            'Q': (20000, 80, 8),
            'F': (40000, 160, 16),
        },
        'WE': {
            'Q': (15000, 60, 6),
            'F': (25000, 100, 10),
        },
        'MJ': {
            'Q': (15000, 60, 6),
            'F': (25000, 100, 10),
        },
        'WJ': {
            'Q': (10000, 40, 4),
            'F': (20000, 80, 8),
        },
    },
    285: {
        'ME': {
            'Q': (20000, 70, 7),
            'F': (40000, 140, 14),
        },
        'WE': {
            'Q': (16000, 56, 5),
            'F': (25000, 84, 8),
        },
        'MJ': {
            'Q': (16000, 56, 5),
            'F': (25000, 84, 8),
        },
        'WJ': {
            'Q': (10000, 35, 3),
            'F': (20000, 70, 7),
        },
    },
    333: {
        'ME': {
            'Q': (20000, 60, 12),
            'F': (40000, 120, 24),
        },
        'WE': {
            'Q': (16000, 48, 9),
            'F': (25000, 75, 15),
        },
        'MJ': {
            'Q': (16000, 48, 9),
            'F': (25000, 75, 15),
        },
        'WJ': {
            'Q': (10000, 30, 6),
            'F': (20000, 60, 12),
        },
    },
    400: {
        'ME': {
            'Q': (20000, 50, 10),
            'F': (40000, 100, 20),
        },
        'WE': {
            'Q': (16000, 40, 8),
            'F': (25000, 65, 13),
        },
        'MJ': {
            'Q': (16000, 40, 8),
            'F': (25000, 65, 13),
        },
        'WJ': {
            'Q': (10000, 25, 5),
            'F': (20000, 50, 10),
        },
    },
}

# Generic Competition Builder Qual/Finals, Medals, Series, Entrants
_PURSUIT_BUILDER = {
    'ctype': {
        'prompt': 'Pursuit',
        'control': 'section',
    },
    'cat': {
        'prompt': 'Category:',
        'control': 'choice',
        'defer': True,
        'hint': 'Competitor category',
    },
    'series': {
        'prompt': 'Number Series:',
        'control': 'short',
        'hint': 'Competitor number series',
        'defer': True,
    },
    'code': {
        'prompt': 'Competition ID:',
        'control': 'short',
        'hint': 'Competition identifier',
        'value': 'pursuit',
        'defer': True,
    },
    'entrants': {
        'prompt': 'Entrants:',
        'control': 'short',
        'type': 'int',
        'hint': 'Optional number of competitors',
        'defer': True,
    },
    'domedals': {
        'prompt': 'Medals:',
        'control': 'check',
        'type': 'bool',
        'subtext': 'Yes?',
        'hint': 'Include Gold Silver Bronze medals in classification',
        'value': False,
        'defer': True,
    },
}

# Font-overrides
DIGITFONT = Pango.FontDescription('Noto Mono Medium 22')
MONOFONT = Pango.FontDescription('Noto Mono')
LOGVIEWFONT = Pango.FontDescription('Noto Mono 11')

# Cell renderer styles
STYLE_ITALIC = Pango.Style.ITALIC
STYLE_NORMAL = Pango.Style.NORMAL

# Timer text
FIELDWIDTH = '00h00:00.0000'
ARMTEXT = '       0.0   '

# Screen Height Limits
MAX_HEIGHT_FACTOR = 0.9  # Limit window natural height to 90% of screen
MAX_HEIGHT_MIN = 520  # Min natural height in case screen info is degenerate


class statButton(Gtk.Box):

    def __init__(self):
        Gtk.Box.__init__(self)
        self.__curbg = 'idle'
        self.__image = Gtk.Image.new_from_icon_name(
            metarace.action_icon(self.__curbg), Gtk.IconSize.BUTTON)
        self.__image.show()
        self.__label = Gtk.Label.new('--')
        self.__label.set_width_chars(12)
        self.__label.set_single_line_mode(True)
        self.__label.show()
        self.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.set_spacing(2)
        self.pack_start(self.__image, False, True, 0)
        self.pack_start(self.__label, True, True, 0)
        self.show()
        self.set_sensitive(False)
        self.set_can_focus(False)

    def update(self, bg=None, label=None):
        """Update button content"""
        if bg is not None and bg != self.__curbg:
            self.__image.set_from_icon_name(metarace.action_icon(bg),
                                            Gtk.IconSize.BUTTON)
            self.__curbg = bg
        if label is not None:
            self.__label.set_text(label)


class traceFilter(logging.Filter):
    """Filter events to type TIMER only."""

    def filter(self, record):
        return record.levelno == 15  # timy._TIMER_LOG_LEVEL


class traceHandler(logging.Handler):
    """Class for capturing timer log traces."""

    def __init__(self, trace=None):
        self.__trace = trace
        logging.Handler.__init__(self)
        self.addFilter(traceFilter())

    def emit(self, record):
        """Append log record to trace."""
        if self.__trace is not None:
            msg = self.format(record)
            self.__trace.append(msg)


class textViewHandler(logging.Handler):
    """A class for displaying log messages in a GTK text view."""

    def __init__(self, log=None, view=None, scroll=None):
        self.log = log
        self.view = view
        self.scroll = scroll
        self.scroll_pending = False
        logging.Handler.__init__(self)

    def do_scroll(self):
        """Catch up end of scrolled window."""
        if self.scroll_pending:
            self.scroll.set_value(self.scroll.get_upper() -
                                  self.scroll.get_page_size())
            self.scroll_pending = False
        return False

    def append_log(self, msg):
        """Append msg to the text view."""
        atend = True
        if self.scroll and self.scroll.get_page_size() > 0:
            # Fudge a 'sticky' end of scroll mode... about a pagesz
            pagesz = self.scroll.get_page_size()
            if self.scroll.get_upper() - (self.scroll.get_value() + pagesz) > (
                    0.5 * pagesz):
                atend = False
        self.log.insert(self.log.get_end_iter(), msg.strip() + '\n')
        if atend:
            self.scroll_pending = True
            GLib.idle_add(self.do_scroll)
        return False

    def emit(self, record):
        """Emit log record to gtk main loop."""
        msg = self.format(record)
        GLib.idle_add(self.append_log, msg)


class statusHandler(logging.Handler):
    """A class for displaying log messages in a GTK status bar."""

    def __init__(self, status=None, context=0):
        self.status = status
        self.context = context
        logging.Handler.__init__(self)

    def pull_status(self, msgid):
        """Remove specified msgid from the status stack."""
        self.status.remove(self.context, msgid)
        return False

    def push_status(self, msg, level):
        """Push the given msg onto the status stack, and defer removal."""
        delay = 3
        if level > 25:
            delay = 8
        msgid = self.status.push(self.context, msg)
        GLib.timeout_add_seconds(delay, self.pull_status, msgid)
        return False

    def emit(self, record):
        """Emit log record to gtk main loop."""
        msg = self.format(record)
        GLib.idle_add(self.push_status, msg, record.levelno)


class timerpane:

    def setrider(self, bib=None, ser=None):
        """Set bib for timer."""
        if bib is not None:
            self.bibent.set_text(bib.upper())
            if ser is not None:
                self.serent.set_text(ser)
            self.bibent.activate()  # and chain events

    def grab_focus(self, data=None):
        """Steal focus into bib entry."""
        self.bibent.grab_focus()
        return False  # allow addition to idle_add or delay

    def getrider(self):
        """Return bib loaded into timer."""
        return self.bibent.get_text().upper()

    def getstatus(self):
        """Return timer status.

        Timer status may be one of:

          'idle'        -- lane empty or ready for new rider
          'load'        -- rider loaded into lane
          'armstart'    -- armed for start trigger
          'running'     -- timer running
          'armint'      -- armed for intermediate split
          'armfin'      -- armed for finish trigger
          'finish'      -- timer finished

        """
        return self.status

    def set_time(self, tstr=''):
        """Set timer string."""
        self.ck.set_text(tstr)

    def get_time(self):
        """Return current timer string."""
        return self.ck.get_text()

    def show_splits(self):
        """Show the split button and label."""
        self.ls.show()
        self.lb.show()

    def hide_splits(self):
        """Hide the split button and label."""
        self.ls.hide()
        self.lb.hide()

    def set_split(self, split=None):
        """Set the split pointer and update label."""
        # update split index from supplied argument
        if isinstance(split, int):
            if split >= 0 and split < len(self.splitlbls):
                self.split = split
            else:
                _log.warning('Requested split %r not in range %r', split,
                             self.splitlbls)
        elif isinstance(split, str):
            if split in self.splitlbls:
                self.split = self.splitlbls.index(split)
            else:
                _log.warning('Requested split %r not found %r', split,
                             self.splitlbls)
        else:
            self.split = -1  # disable label

        # update label to match current split
        if self.split >= 0 and self.split < len(self.splitlbls):
            self.ls.set_text(self.splitlbls[self.split])
        else:
            self.ls.set_text('')

    def on_halflap(self):
        """Return true is current split pointer is a half-lap."""
        return self.split % 2 == 0

    def split_up(self):
        """Increment split to next."""
        self.set_split(self.split + 1)

    def lap_up(self):
        """Increment the split point to the next whole lap."""
        nsplit = self.split
        if self.on_halflap():
            nsplit += 1
        else:
            nsplit += 2
        self.set_split(nsplit)

    def lap_up_clicked_cb(self, button, data=None):
        """Respond to lap up button press."""
        if self.status in ['running', 'armint', 'armfin']:
            self.missedlap()

    def runtime(self, runtod):
        """Update timer run time."""
        if runtod > self.recovtod:
            self.set_time(runtod.timestr(1))

    def missedlap(self):
        """Flag a missed lap to allow 'catchup'."""
        _log.info('No time recorded for split %r', self.split)
        self.lap_up()

    def get_sid(self, inter=None):
        """Return the split id for the supplied, or current split."""
        if inter is None:
            inter = self.split
        ret = None
        if inter >= 0 and inter < len(self.splitlbls):
            ret = self.splitlbls[inter]
        return ret

    def intermed(self, inttod, recov=4):
        """Trigger an intermediate time."""
        nt = inttod - self.starttod
        if self.on_halflap():
            # reduce recover time on half laps
            recov = 2
        self.recovtod.timeval = nt.timeval + recov
        self.set_time(nt.timestr(self.precision))
        self.torunning()

        # store intermedate split in local split cache
        sid = self.get_sid()
        self.splits[sid] = inttod

    def difftime(self, dt):
        """Overwrite split time with a difference time."""
        dstr = ('+' + dt.rawtime(2) + ' ').rjust(12)
        self.set_time(dstr)

    def getsplit(self, inter):
        """Return split for specified passing."""
        ret = None
        sid = self.get_sid(inter)
        if sid in self.splits:
            ret = self.splits[sid]
        return ret

    def finish(self, fintod):
        """Trigger finish on timer."""
        # Note: split pointer is not updated, so after finish, if
        #       labels are loaded, the current split will point to
        #       a dummy sid for event distance
        self.finishtod = fintod
        self.ls.set_text('Finish')
        self.set_time((self.finishtod - self.starttod).timestr(self.precision))
        self.tofinish()

    def tofinish(self, status='finish'):
        """Set timer to finished."""
        self.status = status
        self.b.update('idle', 'Finished')
        self.b.set_sensitive(False)

    def toarmfin(self):
        """Arm timer for finish."""
        self.status = 'armfin'
        self.b.update('error', 'Finish Armed')
        self.b.set_sensitive(True)

    def toarmint(self, label='Lap Armed'):
        """Arm timer for intermediate."""
        self.status = 'armint'
        self.b.update('activity', label)
        self.b.set_sensitive(True)

    def torunning(self):
        """Update timer state to running."""
        self.bibent.set_sensitive(False)
        self.serent.set_sensitive(False)
        self.status = 'running'
        self.b.update('ok', 'Running')
        self.b.set_sensitive(True)

    def start(self, starttod):
        """Trigger start on timer."""
        self.starttod = starttod
        if self.splitlbls:
            self.set_split(0)
        self.torunning()

    def toload(self, bib=None):
        """Load timer."""
        self.status = 'load'
        self.starttod = None
        self.recovtod = tod.tod(0)  # timeval is manipulated
        self.finishtod = None
        self.rearwheel = None
        self.set_time()
        self.splits = {}
        self.set_split()
        if bib is not None:
            self.setrider(bib)
        self.b.update('idle', 'Ready')
        self.b.set_sensitive(True)

    def toarmstart(self):
        """Set state to armstart."""
        self.status = 'armstart'
        self.set_split()
        self.set_time(ARMTEXT)
        self.b.update('activity', 'Start Armed')
        self.b.set_sensitive(True)

    def disable(self):
        """Disable rider bib entry field."""
        self.bibent.set_sensitive(False)
        self.serent.set_sensitive(False)

    def enable(self):
        """Enable rider bib entry field."""
        self.bibent.set_sensitive(True)
        self.serent.set_sensitive(True)

    def toidle(self):
        """Set timer state to idle."""
        self.status = 'idle'
        self.bib = None
        self.bibent.set_text('')
        self.bibent.set_sensitive(True)
        self.serent.set_sensitive(True)
        self.biblbl.set_text('')
        self.starttod = None
        self.recovtod = tod.tod(0)
        self.finishtod = None
        self.rearwheel = None
        self.split = -1  # next expected passing
        self.splits = {}  # map of split ids to split data
        self.set_split()
        self.set_time()
        self.b.update('idle', 'Idle')
        self.b.set_sensitive(False)

    def __init__(self, label='Timer', doser=False):
        """Constructor."""
        _log.debug('Building timerpane: %r', label)
        self.label = label
        self.rearwheel = None
        s = Gtk.Frame.new(label)
        s.set_border_width(5)
        s.set_shadow_type(Gtk.ShadowType.IN)
        s.show()
        self.doser = doser
        self.precision = 3

        v = Gtk.Box.new(Gtk.Orientation.VERTICAL, 5)
        v.set_homogeneous(False)
        v.set_border_width(5)

        # Bib and name label
        h = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 5)
        h.set_homogeneous(False)
        l = Gtk.Label.new('Rider #:')
        l.show()
        h.pack_start(l, False, True, 0)
        self.bibent = Gtk.Entry.new()
        self.bibent.set_width_chars(3)
        self.bibent.show()
        h.pack_start(self.bibent, False, True, 0)
        self.serent = Gtk.Entry.new()
        self.serent.set_width_chars(2)
        if self.doser:
            self.serent.show()
        h.pack_start(self.serent, False, True, 0)
        self.biblbl = Gtk.Label.new('')
        self.biblbl.show()
        h.pack_start(self.biblbl, True, True, 0)

        # mantimer entry
        self.tment = Gtk.Entry.new()
        self.tment.set_width_chars(10)
        h.pack_start(self.tment, False, True, 0)
        #h.set_focus_chain([self.bibent, self.tment, self.bibent])
        h.show()

        v.pack_start(h, False, True, 0)

        # Clock row 'HHhMM:SS.DCMZ'
        self.ck = Gtk.Label.new(FIELDWIDTH)
        self.ck.set_alignment(0.5, 0.5)
        self.ck.modify_font(DIGITFONT)
        self.ck.show()
        v.pack_start(self.ck, True, True, 0)

        # Timer ctrl/status button
        h = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 5)
        h.set_homogeneous(False)

        b = Gtk.Button.new()
        b.show()
        b.set_property('can-focus', False)
        self.b = statButton()
        b.add(self.b)
        self.b.update('idle', 'Idle')
        h.pack_start(b, True, True, 0)
        self.ls = Gtk.Label.new('')
        h.pack_start(self.ls, False, True, 0)
        self.lb = Gtk.Button.new_with_label('+')
        self.lb.set_border_width(5)
        self.lb.set_property('can-focus', False)
        self.lb.connect('clicked', self.lap_up_clicked_cb)
        h.pack_start(self.lb, False, True, 0)
        h.show()
        v.pack_start(h, False, True, 0)
        v.show()
        s.add(v)
        self.frame = s
        self.splitlbls = []  # ordered set of split ids
        self.toidle()


def builder(resource=None):
    """Create and return a Gtk.Builder loaded from named resource"""
    ret = None
    _log.debug('Creating Gtk Builder for resource %r', resource)
    rf = files(RESOURCE_PKG).joinpath(resource)
    if rf is not None and rf.is_file():
        ret = Gtk.Builder()
        ret.add_from_string(rf.read_text(encoding='utf-8'))
    else:
        _log.error('Unable to read resource %r: %r', resource, rf)
    return ret


def do_update_done(status=None):
    """Report update result."""
    if status is not None:
        if status:
            _log.warning('Update complete - restart required')
        else:
            _log.info('Update not required')
    else:
        _log.warning('Unable to complete update')

    _UPDATE_PROC['run']['lock'].release()
    return None


def do_update(packages=None):
    """Trigger update with a completion callback."""
    if not _UPDATE_PROC['run']['lock'].acquire(False):
        _log.info('Update/check already in progress')
        return None
    tp = threading.Thread(target=run_update,
                          kwargs={
                              'packages': packages,
                              'callback': do_update_done,
                          },
                          daemon=True)
    tp.start()
    _UPDATE_PROC['run']['thread'] = tp
    return None


def run_update(packages=[], callback=None):
    """Update packages in virtual env using pip"""
    ret = None
    try:
        if packages:
            if sys.prefix == sys.base_prefix:
                raise RuntimeError('Not in virtual env, update aborted')

            venv = os.path.join(metarace.DATA_PATH, 'venv')
            if not sys.prefix == venv:
                raise RuntimeError('Outside data path, update aborted')

            _log.info('Updating packages: %s', ', '.join(
                (p[0] for p in packages)))
            cmd = [
                os.path.join(venv, 'bin', 'pip'),
                'install',
                '-U',
                '--no-color',
                '--progress-bar',
                'off',
            ]
            cmd.extend((p[0] for p in packages))
            res = run(cmd, encoding='utf-8', capture_output=True)
            if res.stdout:
                _log.debug('pip install output:')
                for l in res.stdout.split('\n'):
                    if l.rstrip():
                        _log.debug(' %s', l)
            _log.info('Update complete')
            ret = True
        else:
            _log.info('No updates to install')
            ret = False
    except Exception as e:
        _log.error('%s updating: %s', e.__class__.__name__, e)
    finally:
        if callback is not None:
            GLib.idle_add(callback, ret)


def do_update_check_done(updates=None, window=None):
    """Report update check result and optionally start install."""
    if updates is not None:
        if updates:
            _log.info('Updated packages available to install')
            msg = ['New packages available to install:', '']
            for p in updates:
                msg.append(' - %s %s => %s' % p)
            if questiondlg(window=window,
                           question='Install updates?',
                           subtext='\n'.join(msg),
                           title='Updated Packages Available'):
                GLib.idle_add(do_update, updates)
            else:
                _log.info('Updates not installed')
        else:
            _log.info('Installation up to date')
    else:
        _log.warning('Unable to check for updates')

    _UPDATE_PROC['check']['lock'].release()
    return None


def do_update_check(window=None):
    """Trigger update check with a completion callback."""
    if not _UPDATE_PROC['check']['lock'].acquire(False):
        _log.info('Update/check already in progress')
        return None
    tp = threading.Thread(target=run_update_check,
                          kwargs={
                              'callback': do_update_check_done,
                              'window': window
                          },
                          daemon=True)
    tp.start()
    _UPDATE_PROC['check']['thread'] = tp
    return None


def run_update_check(callback=None, window=None):
    """Check for updated packages using pip"""
    ret = None
    try:
        if sys.prefix == sys.base_prefix:
            raise RuntimeError('Not in virtual env, update aborted')

        venv = os.path.join(metarace.DATA_PATH, 'venv')
        if not sys.prefix == venv:
            raise RuntimeError('Outside data path, update aborted')

        _log.info('Checking for updates on Python Package Index')
        cmd = (
            os.path.join(venv, 'bin', 'pip'),
            'list',
            '-l',
            '--format',
            'json',
            '--outdated',
            '--exclude',
            'pip',
            '--exclude',
            'setuptools',
        )
        res = run(cmd, encoding='utf-8', capture_output=True)
        if res.stdout:
            ret = []
            updates = json.loads(res.stdout)
            for package in updates:
                name = package['name']
                version = package['version']
                latest_version = package['latest_version']
                if name and name in _ALLOWED_UPDATES:
                    ret.append((
                        name,
                        version,
                        latest_version,
                    ))
                    _log.debug('%s %s -> %s', name, version, latest_version)
    except Exception as e:
        _log.error('%s checking for updates: %s', e.__class__.__name__, e)
    finally:
        if callback is not None:
            GLib.idle_add(callback, ret, window)


def run_standards_update():
    """Perform standards update."""
    f = Factors()
    f.update()
    c = CategoryInfo()
    c.update()
    _UPDATE_PROC['standards']['lock'].release()
    _UPDATE_PROC['standards']['thread'] = None


def do_standards_update(window=None):
    """Trigger standards update."""
    if not _UPDATE_PROC['standards']['lock'].acquire(False):
        _log.info('Standards update already in progress')
        return None
    tp = threading.Thread(target=run_standards_update, daemon=True)
    tp.start()
    _UPDATE_PROC['standards']['thread'] = tp
    return tp


def comp_builder(window, meet, comptype):
    """Build a standards-based competition and add to meet."""
    label = None
    options_schema = None
    comptable = None
    catinfo = CategoryInfo()
    catinfo.load()
    title = 'Add Competition'
    catlist = {}
    for c, info in catinfo._store.items():
        if info['Discipline'] in ('all', 'track'):
            lbl = '%s: %s' % (c, info['Title'])
            catlist[c] = lbl
    if comptype in ('pursuit', 'individual pursuit'):
        comptype = 'individual pursuit'
        label = 'Individual Pursuit'
        options_schema = _PURSUIT_BUILDER
        # Overwrite schema values as required
        options_schema['ctype']['prompt'] = label
        options_schema['cat']['options'] = catlist
        options_schema['series']['value'] = ''
        options_schema['code']['value'] = 'ip'
    elif comptype == 'team pursuit':
        label = 'Team Pursuit'
        options_schema = _PURSUIT_BUILDER
        # Overwrite schema values as required
        options_schema['ctype']['prompt'] = label
        options_schema['cat']['options'] = catlist
        options_schema['series']['value'] = 'tp'
        options_schema['code']['value'] = 'tp'
    elif comptype == 'team sprint':
        label = 'Team Sprint'
        options_schema = _PURSUIT_BUILDER
        # Overwrite schema values as required
        options_schema['ctype']['prompt'] = label
        options_schema['cat']['options'] = catlist
        options_schema['series']['value'] = 'ts'
        options_schema['code']['value'] = 'ts'
    elif comptype == 'time trial':
        label = 'Time Trial'

        options_schema = _PURSUIT_BUILDER
        # Overwrite schema values as required
        options_schema['ctype']['prompt'] = label
        options_schema['cat']['options'] = catlist
        options_schema['series']['value'] = ''
        options_schema['code']['value'] = 'tt'
    elif comptype in ('sprint', 'olympic sprint'):
        if comptype == 'olympic sprint':
            comptable = _OLY_SPRINT_COMPETITION
        else:
            comptable = _SPRINT_COMPETITION
        label = 'Sprint'
        options_schema = _PURSUIT_BUILDER
        # Overwrite schema values as required
        options_schema['ctype']['prompt'] = label
        options_schema['cat']['options'] = catlist
        options_schema['series']['value'] = ''
        options_schema['code']['value'] = 'sprint'
    elif comptype in ('scratch race', 'points race', 'elimination race',
                      'madison'):
        label = comptype.title()
        if comptype in _COMPIDS:
            comptype = _COMPIDS[comptype]  # scratch race => scratch
        options_schema = _PURSUIT_BUILDER
        options_schema['ctype']['prompt'] = label
        options_schema['cat']['options'] = catlist
        options_schema['series']['value'] = ''
        options_schema['code']['value'] = comptype

    if options_schema is None:
        _log.info('Missing schema for %s builder', comptype)
        return

    res = options_dlg(window=window,
                      title=title,
                      action=True,
                      sections={
                          'comp': {
                              'title': 'Competition',
                              'schema': options_schema,
                              'object': {},
                          }
                      })
    if res['action'] == 0:  # OK
        if res['comp']['cat'][2]:  # cat is defined
            cat = res['comp']['cat'][2]
            category = catinfo.get_cat(cat)
            masters = catinfo.is_masters(cat)
            u13 = catinfo.is_u13(cat)
            u17 = catinfo.is_u17(cat)
            meet.addcat(cat, category['Title'])
            series = res['comp']['series'][2]
            code = res['comp']['code'][2]
            entrants = res['comp']['entrants'][2]
            dofinals = True
            if u13:
                _log.info('Qualifying phase skipped for Under 13 category')
                dofinals = False
            domedals = res['comp']['domedals'][2]
            _log.debug('Building competition for cat=%s code=%s', cat, code)
            if comptype in ('individual pursuit', 'team pursuit',
                            'team sprint'):
                if entrants is None:
                    entrants = 5  # assume full competition
                elif entrants < 2:
                    dofinals = False
                build_pursuit_comp(meet, label, cat, category, series, code,
                                   dofinals, domedals, entrants)
            elif comptype in ('time trial'):
                if masters:
                    if dofinals:
                        _log.info(
                            'Qualifying phase skipped for masters category')
                    dofinals = False
                if entrants is None:
                    entrants = 9  # assume full competition
                elif entrants < 9:
                    dofinals = False
                build_itt_comp(meet, label, cat, category, series, code,
                               dofinals, domedals, entrants)
            elif comptype in ('sprint', 'olympic sprint'):
                # adjust 1/4 final heats for youth and masters (applies to both tables)
                if (meet.domestic and masters) or u13 or u17:
                    comptable['1.4']['heats'] = 1
                else:
                    comptable['1.4']['heats'] = 3
                if entrants is None:
                    entrants = 8  # assume a minimum number 3.2.031
                elif entrants < 2:
                    _log.info('Degenerate sprint competition for %s category',
                              cat)
                    dofinals = False
                build_sprint_comp(meet, label, cat, category, series, code,
                                  dofinals, domedals, entrants, comptable)
            elif comptype in ('scratch', 'points', 'elimination', 'madison'):
                trackmax = meet.get_competitor_limit(
                    madison=comptype == 'madison')
                if entrants is None:
                    entrants = 1  # assume no heats required
                if u13 and entrants > trackmax:
                    _log.info(
                        'Track maximum exceeded for %d U13 entrants in %s',
                        entrants, label)
                    entrants = trackmax
                    dofinals = False
                elif entrants <= trackmax:
                    _log.info('Qualifying skipped for <%d entrants in %s',
                              trackmax, label)
                    dofinals = False
                build_bunch_comp(meet, label, cat, category, series, code,
                                 dofinals, domedals, entrants, trackmax,
                                 comptype, masters)
        else:
            _log.info('No cat selected for new competion')
    return False


def comp_label_short(label):
    """Return a short, ~2 character id for the given competition label."""
    ret = ''
    lcheck = label.lower().translate(strops.WEBFILE_UTRANS)

    if lcheck in _COMPABBREVS:
        ret = _COMPABBREVS[lcheck]
    else:
        ret = lcheck[0:2]
    return ret


def _normdep(srcmap, idmap={}):
    """Convert srcmap to dependency string substituting event ids from idmap."""
    rv = []
    for src in srcmap:
        evid = src
        if src in idmap:
            evid = idmap[src]
        rv.append(evid)
    return ' '.join(rv)


def _normauto(srcmap, idmap={}):
    """Convert srcmap to autostart string substituting event ids from idmap."""
    rv = []
    for src, places in srcmap.items():
        evid = src
        if src in idmap:
            evid = idmap[src]
        rv.append('%s: %s' % (evid, places))
    return '; '.join(rv)


def build_sprint_comp(meet, label, cat, category, series, code, dofinals,
                      domedals, entrants, comptable):
    """Create sprint events, add to meet."""
    laps = 3  # applies to sprint rounds only
    laplen = meet.get_laplen()
    if laplen >= 333.33:  # 3.2.035
        laps = 2
    distance = '200\u2006m, flying start'  # applies to qualifying only

    if not entrants:
        entrants = 8  # 3.2.031

    # check and clean competition code
    if code is not None:
        code = code.translate(strops.PRINT_UTRANS).strip()
    else:
        code = ''
    if not code:
        code = label.lower().translate(strops.WEBFILE_UTRANS)

    # ensure series is set
    if series is None:
        series = ''

    qualtype = 'flying 200'
    roundtype = 'sprint round'
    finaltype = 'sprint final'
    derbytype = 'derby'
    pseudotype = 'sprint heat'

    # find an unused event id for the catcomp
    compid = comp_label_short(label)
    catcomp = cat.lower() + compid
    count = 1
    while catcomp in meet.edb:
        count += 1
        catcomp = '%s%s%d' % (cat.lower(), compid, count)

    prefix = '%s %s' % (
        category['Title'],
        label,
    )

    if dofinals:
        # construct phases as per 3.2.050
        idmap = {}
        eventlist = []  # event ids to be reported with result
        placeslist = []  # places in the final classification
        otherslist = []  # ranked together according to 200m TT
        othersrc = None  # id of 200m TT

        # Determine first phase of competition after qualifying
        phase = 'final'
        phaselabel = 'Final'
        nrqual = min(4, entrants)
        if entrants >= 4:
            for pid, detail in comptable.items():
                if detail['firstround'] and entrants >= detail['entrants']:
                    _log.debug('First sprint phase: %s %s', pid,
                               detail['label'])
                    phase = pid
                    phaselabel = detail['label']
                    nrqual = detail['entrants']
                    break
        nrdep = ''
        nrstart = ''

        # qualifying
        qrule = ''
        if entrants >= 4:
            # add qrule even when entrants == nrqual;
            qrule = 'Top %d to %s' % (nrqual, phaselabel)
        elif entrants == 3:
            qrule = '1st&2nd to gold final; 3rd bronze'
            nrqual = 2
        elif entrants == 2:
            qrule = 'Top 2 to gold final'
            nrqual = 2
        pqid = '%sq' % (catcomp, )
        idmap['qualifying'] = pqid
        othersrc = pqid
        pqev = meet.edb.add_empty(evno=pqid, notify=False)
        pqev.set_values({
            'series': series,
            'reference': catcomp,
            'type handler': qualtype,
            'prefix': prefix,
            'info': 'Qualifying',
            'result': False,
            'index': True,
            'program': True,
            'qualifiers': nrqual,
            'distance': distance,
            'rules': qrule,
            'category': cat,
            'competion': code,
            'phase': 'qualifying',
        })
        eventlist.insert(0, pqid)
        minplace = nrqual + 1
        if minplace <= entrants:
            # at least one plain other
            otherslist.append('%s:%d-' % (pqid, minplace))

        # send qualified to next round - manually, ignore the table for now
        nrdep = pqid
        nrstart = '%s: 1-%s' % (pqid, nrqual)

        # other phases
        while phase is not None:
            detail = comptable[phase]

            if nrdep is None:
                srcobj = detail['source'].copy()
                if phase == '1.16' and '1.32a' in srcobj:
                    # Oly sprint special case, choose 1/32 or 1/32 based on entrants
                    if entrants < 32:
                        del (srcobj['1.32a'])
                    else:
                        # assume 'AU' override, single heat 1/32 to 16 competitors
                        del (srcobj['1.32'])
                nrdep = _normdep(srcobj, idmap)
                nrstart = _normauto(srcobj, idmap)

            pcount = detail['entrants']
            if phase == 'final' and entrants < 4:
                pcount = 2  # for gold only final

            einfo = detail['label']
            etype = roundtype
            phrule = []
            if detail['heats'] > 1:
                etype = finaltype
                phrule.append('Best of 3 heats')
            elif detail['heats'] == 0:
                etype = derbytype
            qcount = detail['qualifiers']
            if detail['rule'] and qcount != pcount or phase == '1.2':
                phrule.append(detail['rule'])

            # phase head
            phid = '%s%s' % (catcomp, detail['evid'])
            idmap[phase] = phid
            phev = meet.edb.add_empty(evno=phid, notify=False)
            phev.set_values({
                'series': series,
                'reference': catcomp,
                'type handler': etype,
                'prefix': prefix,
                'info': einfo,
                'result': False,
                'index': True,
                'program': True,
                'depends': nrdep,
                'auto': nrstart,
                'placeholders': pcount,
                'laps': laps,
                'rules': '; '.join(phrule),
                'category': cat,
                'competion': code,
                'phase': phase,
            })
            # heat 2/3 dummy events
            if detail['heats'] > 1:
                h2id = '%s%s%s' % (catcomp, detail['evid'], 'h2')
                h2ev = meet.edb.add_empty(evno=h2id, notify=False)
                h2label = einfo + ' Heat 2'
                h2ev.set_values({
                    'series': series,
                    'reference': phid,  # dummies point to phase head
                    'type handler': pseudotype,
                    'prefix': prefix,
                    'info': h2label,
                    'result': False,
                    'index': True,
                    'laps': laps,
                    'rules': '; '.join(phrule),
                    'program': True,
                })
                h3id = '%s%s%s' % (catcomp, detail['evid'], 'h3')
                h3ev = meet.edb.add_empty(evno=h3id, notify=False)
                h3label = einfo + ' Heat 3'
                h3ev.set_values({
                    'series': series,
                    'reference': phid,  # dummies point to phase head
                    'type handler': pseudotype,
                    'prefix': prefix,
                    'info': h3label,
                    'result': False,
                    'index': True,
                    'laps': laps,
                    'rules': '; '.join(phrule),
                    'program': True,
                })
            # save heat references to phase head
            if etype != derbytype:
                c = meet.get_event(phid)
                c.readonly = False
                c.loadconfig()
                if detail['heats'] > 1:
                    c.heat2evno = h2id
                    c.heat3evno = h3id
                c.otherstime = detail['otherstime']
                c.saveconfig()
                c = None

            # Append any decided places to classification
            eventlist.insert(0, phid)
            if phase == 'final':
                if pcount == 2:
                    placeslist.insert(0, '%s: 1,2' % (phid, ))
                if pcount == 4 and detail['places'] is not None:
                    placeslist.insert(0, '%s: %s' % (phid, detail['places']))
            else:
                if detail['places'] is not None:
                    placeslist.insert(0, '%s: %s' % (phid, detail['places']))

            # Group others in classification if required
            if detail['others']:
                otherslist.insert(0, '%s: %s' % (phid, detail['others']))

            # advance to next phase
            phase = detail['next']
            nrdep = None
            nrstart = None

        # classification
        showevs = ' '.join(eventlist)
        places = '; '.join(placeslist)
        pev = meet.edb.add_empty(evno=catcomp, notify=True)
        pev.set_values({
            'series': series,
            'type handler': 'classification',
            'prefix': prefix,
            'result': True,
            'index': False,
            'program': False,
            'depends': showevs,
            'auto': places,
            'category': cat,
            'competion': code,
        })
        c = meet.get_event(catcomp)
        c.readonly = False
        c.loadconfig()
        if domedals:
            c.medals = 'Gold Silver Bronze'
        if othersrc:
            c.othersrc = othersrc
        if otherslist:
            c.others = '; '.join(otherslist)
        c.showevents = showevs
        c.saveconfig()
        c = None

    else:
        # flying 200m only
        pev = meet.edb.add_empty(evno=catcomp, notify=True)
        pev.set_values({
            'series': series,
            'type handler': qualtype,
            'prefix': prefix,
            'info': 'Final',
            'result': True,
            'index': True,
            'program': True,
            'laps': '',
            'distance': distance,
            'category': cat,
            'competion': code,
            'phase': 'final',
        })


def bunch_heats(limit, entrants):
    """Return number of heats, rejects per heat and number of finalists."""
    if entrants <= limit:
        return (0, 0, entrants)

    # otherwise heats will be required
    heats = ceil(entrants / limit)
    perheat = ceil(entrants / heats)
    accepted = floor(limit / heats)
    rejected = max(2, perheat - accepted)
    totrejected = heats * rejected
    finalists = entrants - totrejected
    return (heats, rejected, finalists)


def sprint_laps(laps, meet):
    """Return a list of sprint laps for the points race."""
    lapspersprint = 10
    if meet.get_laplen() > 333.0:
        lapspersprint = 5
    ret = []
    sprintlap = 0
    sprintlaps = floor(laps / lapspersprint)
    for s in range(sprintlaps):
        ret.insert(0, str(sprintlap))
        sprintlap += lapspersprint
    return ret


def build_bunch_comp(meet, label, cat, category, series, code, dofinals,
                     domedals, entrants, trackmax, comptype, masters):
    """Create bunch events, add to meet."""

    # is a qualifying round required
    doqual = dofinals
    heats, rejected, finalists = bunch_heats(trackmax, entrants)

    # check and clean competition code
    if code is not None:
        code = code.translate(strops.PRINT_UTRANS).strip()
    else:
        code = ''
    if not code:
        code = label.lower().translate(strops.WEBFILE_UTRANS)

    # ensure series is set
    if series is None:
        series = ''

    # set event types
    finaltype = comptype
    qualtype = comptype

    # setup distances for finals
    dm = None
    distance = None
    laps = None
    if comptype == 'elimination':
        # [3.2.219]
        qualtype = 'scratch'
    else:
        if category[label]:
            laps = None
            dm = category[label]
            distance = '%0.1f\u2006km' % (dm / 1000, )
            lc = meet.tracklen_d * dm / meet.tracklen_n
            if (lc - int(lc)) < 0.25:  # probably even-ish
                laps = int(lc)

    # find an unused event id for the catcomp
    compid = comp_label_short(label)
    catcomp = cat.lower() + compid
    count = 1
    while catcomp in meet.edb:
        count += 1
        catcomp = '%s%s%d' % (cat.lower(), compid, count)

    prefix = '%s %s' % (
        category['Title'],
        label,
    )

    finalsprints = []
    tenpoints = False
    lastdouble = False
    if comptype in ('madison', 'points'):
        lastdouble = True
        if meet.domestic:
            # assume AU override for last lap & ten points/lap
            if dm and dm < 15000:
                tenpoints = True
                lastdouble = False
        else:
            # [3.9.006]
            if masters and dm and dm < 20000:
                tenpoints = True
        # build sprints based on lap count
        finalsprints = sprint_laps(laps, meet)
    _log.debug(
        '%s: %s finalsprints=%r, tenpoints=%r, lastdouble=%r, distance=%r, laps=%r, entrants=%r, rejected=%r, finalists=%r',
        comptype, cat, finalsprints, tenpoints, lastdouble, dm, laps, entrants,
        rejected, finalists)

    if dofinals:
        # Build qualifying and final phases as per 3.2.115, 3.2.157,
        # 3.2.175, 3.2.219
        otherslist = []
        eventlist = []
        heatm = None
        heatdistance = None
        heatlaps = None
        heatlabel = '%s Qualifying' % (qualtype.title(), )
        heattenpoints = False
        heatlastdouble = False

        if heatlabel in category and category[heatlabel]:
            heatm = category[heatlabel]
            heatdistance = '%0.1f\u2006km' % (heatm / 1000, )
            lc = meet.tracklen_d * heatm / meet.tracklen_n
            if (lc - int(lc)) < 0.25:  # probably even-ish
                heatlaps = int(lc)
        if not heatm and masters:
            # try to determine heats at half distance [3.9.006]
            if dm:
                heatm = dm // 2
                heatdistance = '%d\u2006m' % (heatm, )
                lc = meet.tracklen_d * heatm / meet.tracklen_n
                if (lc - int(lc)) < 0.01:  # probably even
                    heatlaps = int(lc)
        heatsprints = []
        if qualtype in ('madison', 'points'):
            heatlastdouble = True
            if meet.domestic:
                # assume AU override for last lap & ten points/lap
                if heatm and heatm < 15000:
                    heattenpoints = True
                    heatlastdouble = False
            else:
                # [3.9.006]
                if masters and heatm and heatm < 20000:
                    heattenpoints = True
            if heatlaps:
                heatsprints = sprint_laps(heatlaps, meet)

        _log.debug(
            '%s: %s %d heats heatlen=%r heatlaps=%r heatsprints=%r, heattenpoints=%r, heatlastdouble=%r',
            qualtype, cat, heats, heatm, heatlaps, heatsprints, heattenpoints,
            heatlastdouble)
        riders = 'riders'
        if comptype == 'madison' or series.startswith('t'):
            riders = 'teams'
        for h in range(heats):
            heat = h + 1
            iline = 'Qualifying Heat %d' % (heat, )
            rline = ''
            if rejected:
                # will be 0 or 2+
                rline = '%d %s eliminated' % (rejected, riders)
            qhid = '%sq%d' % (catcomp, heat)
            eventlist.append(qhid)
            qhev = meet.edb.add_empty(evno=qhid, notify=False)
            qhev.set_values({
                'series': series,
                'type handler': qualtype,
                'prefix': prefix,
                'info': iline,
                'result': False,
                'index': True,
                'program': True,
                'laps': heatlaps,
                'distance': heatdistance,
                'rule': rline,
                'qualifiers': -rejected,
                'category': cat,
                'competion': code,
                'phase': 'qualifying',
                'contest': str(heat),
            })
            if qualtype in ('madison', 'points'):
                c = meet.get_event(qhid)
                c.readonly = False
                c.loadconfig()
                if tenpoints:
                    c.tenptlaps = True
                if lastdouble:
                    c.sprintpoints['0'] = '10 6 4 2'
                c.sprintlaps = ' '.join(heatsprints)
                c.sprint_model_init()
                c.saveconfig()
                c = None
            # qualified riders handled by topn
            # unqualified riders grouped as others
            otherslist.append('%s:-Q' % (qhid, ))
        # then add final
        fid = '%sf' % (catcomp, )
        eventlist.insert(0, fid)
        fev = meet.edb.add_empty(evno=fid, notify=False)
        fev.set_values({
            'series': series,
            'type handler': finaltype,
            'prefix': prefix,
            'info': 'Final',
            'result': True,
            'index': True,
            'program': True,
            'laps': laps,
            'distance': distance,
            'category': cat,
            'competion': code,
            'phase': 'final',
        })
        if comptype in ('madison', 'points'):
            c = meet.get_event(fid)
            c.readonly = False
            c.loadconfig()
            if tenpoints:
                c.tenptlaps = True
            if lastdouble:
                c.sprintpoints['0'] = '10 6 4 2'
            c.sprintlaps = ' '.join(finalsprints)
            c.sprint_model_init()
            c.saveconfig()
            c = None
        # classification
        showevs = ' '.join(eventlist)
        places = fid
        pev = meet.edb.add_empty(evno=catcomp, notify=True)
        pev.set_values({
            'series': series,
            'type handler': 'classification',
            'prefix': prefix,
            'result': True,
            'index': False,
            'program': False,
            'depends': showevs,
            'auto': places,
            'category': cat,
            'competion': code,
        })
        c = meet.get_event(catcomp)
        c.readonly = False
        c.loadconfig()
        if otherslist:
            c.others = '; '.join(otherslist)
        if domedals:
            c.medals = 'Gold Silver Bronze'
        c.showevents = showevs
        c.saveconfig()
        c = None
    else:
        # straight final
        pev = meet.edb.add_empty(evno=catcomp, notify=True)
        pev.set_values({
            'series': series,
            'type handler': finaltype,
            'prefix': prefix,
            'info': 'Final',
            'result': True,
            'index': True,
            'program': True,
            'laps': laps,
            'distance': distance,
            'category': cat,
            'competion': code,
            'phase': 'final',
        })
        if comptype in ('madison', 'points'):
            c = meet.get_event(catcomp)
            c.readonly = False
            c.loadconfig()
            if tenpoints:
                c.tenptlaps = True
            if lastdouble:
                c.sprintpoints['0'] = '10 6 4 2'
            c.sprintlaps = ' '.join(finalsprints)
            c.sprint_model_init()
            c.saveconfig()
            c = None


def build_pursuit_comp(meet, label, cat, category, series, code, dofinals,
                       domedals, entrants):
    """Create pursuit-like events, add to meet."""
    laps = None
    distance = ''
    if label == 'Team Sprint':
        # assume three riders unless overridden
        laps = 3
        if category[label]:
            laps = category[label]
        dm = laps * meet.tracklen_n / meet.tracklen_d
        distance = '%0.0f\u2006m' % (dm, )
    elif category[label]:
        dm = category[label]
        distance = '%d\u2006m' % (dm, )
        lc = meet.tracklen_d * dm / meet.tracklen_n
        if (lc - int(lc)) < 0.01:  # probably even
            laps = int(lc)

    # check and clean competition code
    if code is not None:
        code = code.translate(strops.PRINT_UTRANS).strip()
    else:
        code = ''
    if not code:
        code = label.lower().translate(strops.WEBFILE_UTRANS)

    # ensure series is set
    if series is None:
        series = ''

    qualtype = 'indiv pursuit'
    finaltype = 'pursuit race'
    if label == 'Team Sprint':
        qualtype = 'team sprint'
        finaltype = 'team sprint race'
    elif label == 'Team Pursuit':
        qualtype = 'team pursuit'
        finaltype = 'team pursuit race'

    # find an unused event id for the catcomp
    compid = comp_label_short(label)
    catcomp = cat.lower() + compid
    count = 1
    while catcomp in meet.edb:
        count += 1
        catcomp = '%s%s%d' % (cat.lower(), compid, count)

    prefix = '%s %s' % (
        category['Title'],
        label,
    )

    if dofinals:
        # Build qualifying and final phases as per 3.2.052
        eventlist = []  # event ids to be reported with result
        placeslist = []  # places in the final classification
        otherslist = []  # unqualified competitors
        othersrc = None  # ranking basis for others

        pqid = '%sq' % (catcomp, )
        pqev = meet.edb.add_empty(evno=pqid, notify=False)
        qrule = '1st&2nd to gold final; 3rd&4th to bronze'
        pqual = 4
        if entrants == 3:
            qrule = '1st & 2nd to gold final'
            pqual = 2
        pqev.set_values({
            'series': series,
            'reference': catcomp,
            'type handler': qualtype,
            'prefix': prefix,
            'info': 'Qualifying',
            'result': False,
            'index': True,
            'program': True,
            'qualifiers': pqual,
            'laps': laps,
            'distance': distance,
            'rules': qrule,
            'category': cat,
            'competion': code,
            'phase': 'qualifying',
        })
        eventlist.insert(0, pqid)
        minplace = pqual + 1
        if minplace <= entrants:
            # at least one other
            otherslist.append('%s:%d-' % (pqid, minplace))
            othersrc = pqid

        # bronze final: 4 or more entrants (masters AU:3.02.02)
        if entrants > 3:
            pfbid = '%sfb' % (catcomp, )
            pfbev = meet.edb.add_empty(evno=pfbid, notify=False)
            pfbev.set_values({
                'series': series,
                'reference': catcomp,
                'type handler': finaltype,
                'prefix': prefix,
                'info': 'Bronze Final',
                'result': False,
                'index': True,
                'program': True,
                'depends': pqid,
                'auto': '%s: 3,4' % (pqid, ),
                'placeholders': 2,
                'laps': laps,
                'distance': distance,
                'category': cat,
                'competion': code,
                'phase': 'final',
                'contest': 'bronze',
            })
            eventlist.insert(0, pfbid)
            placeslist.insert(0, '%s: 1,2' % (pfbid, ))

        # gold final
        pfgid = '%sfg' % (catcomp, )
        pfgev = meet.edb.add_empty(evno=pfgid, notify=False)
        pfgev.set_values({
            'series': series,
            'reference': catcomp,
            'type handler': finaltype,
            'prefix': prefix,
            'info': 'Gold Final',
            'result': False,
            'index': True,
            'program': True,
            'depends': pqid,
            'auto': '%s: 1,2' % (pqid, ),
            'placeholders': 2,
            'laps': laps,
            'distance': distance,
            'category': cat,
            'competion': code,
            'phase': 'final',
            'contest': 'gold',
        })
        eventlist.insert(0, pfgid)
        placeslist.insert(0, '%s: 1,2' % (pfgid, ))

        # classification
        showevs = ' '.join(eventlist)
        places = '; '.join(placeslist)
        pev = meet.edb.add_empty(evno=catcomp, notify=True)
        pev.set_values({
            'series': series,
            'type handler': 'classification',
            'prefix': prefix,
            'result': True,
            'index': False,
            'program': False,
            'depends': showevs,
            'auto': places,
            'category': cat,
            'competion': code,
        })
        c = meet.get_event(catcomp)
        c.readonly = False
        c.loadconfig()
        if otherslist:
            c.others = '; '.join(otherslist)
        if othersrc:
            c.othersrc = othersrc
        if domedals:
            c.medals = 'Gold Silver Bronze'
        c.showevents = showevs
        c.saveconfig()
        c = None
    else:
        # straight final
        pev = meet.edb.add_empty(evno=catcomp, notify=True)
        pev.set_values({
            'series': series,
            'type handler': finaltype,
            'prefix': prefix,
            'info': 'Final',
            'result': True,
            'index': True,
            'program': True,
            'laps': laps,
            'distance': distance,
            'category': cat,
            'competion': code,
            'phase': 'final',
        })


def build_itt_comp(meet, label, cat, category, series, code, dofinals,
                   domedals, entrants):
    """Create time trial events, add to meet."""
    laps = None
    distance = ''
    if category[label]:
        dm = category[label]
        distance = '%d\u2006m' % (dm, )
        lc = meet.tracklen_d * dm / meet.tracklen_n
        if (lc - int(lc)) < 0.01:  # probably even
            laps = int(lc)

    # check and clean competition code
    if code is not None:
        code = code.translate(strops.PRINT_UTRANS).strip()
    else:
        code = ''
    if not code:
        code = label.lower().translate(strops.WEBFILE_UTRANS)

    # ensure series is set
    if series is None:
        series = ''

    # find an unused event id for the catcomp
    compid = comp_label_short(label)
    catcomp = cat.lower() + compid
    count = 1
    while catcomp in meet.edb:
        count += 1
        catcomp = '%s%s%d' % (cat.lower(), compid, count)

    prefix = '%s %s' % (
        category['Title'],
        label,
    )

    if dofinals:
        # qualifying round, 2-up to select best 8 as per 3.2.106
        eventlist = []  # event ids to be reported with result
        placeslist = []  # places in the final classification
        otherslist = []  # unqualified competitors
        othersrc = None  # ranking basis for others

        pqid = '%sq' % (catcomp, )
        pqev = meet.edb.add_empty(evno=pqid, notify=False)
        pqev.set_values({
            'series': series,
            'reference': catcomp,
            'type handler': 'indiv tt',
            'prefix': prefix,
            'info': 'Qualifying',
            'result': False,
            'index': True,
            'program': True,
            'qualifiers': 8,
            'laps': laps,
            'distance': distance,
            'rules': 'Top 8 to final',
            'category': cat,
            'competion': code,
            'phase': 'qualifying',
        })
        c = meet.get_event(pqid)
        c.readonly = False
        c.loadconfig()
        c.timetype = 'dual'
        c.saveconfig()
        c = None
        eventlist.insert(0, pqid)
        if entrants > 8:
            # at least one other
            otherslist.append('%s:%d-' % (pqid, 9))
            othersrc = pqid

        # final - 1 up, top 8
        pfid = '%sf' % (catcomp, )
        pfev = meet.edb.add_empty(evno=pfid, notify=False)
        pfev.set_values({
            'series': series,
            'reference': catcomp,
            'type handler': 'indiv tt',
            'prefix': prefix,
            'info': 'Final',
            'result': False,
            'index': True,
            'program': True,
            'depends': pqid,
            'auto': '%s:1-8' % (pqid, ),
            'placeholders': 8,
            'laps': laps,
            'distance': distance,
            'category': cat,
            'competion': code,
            'phase': 'final',
        })
        c = meet.get_event(pfid)
        c.readonly = False
        c.loadconfig()
        c.timetype = 'single'
        c.saveconfig()
        c = None
        eventlist.insert(0, pfid)
        placeslist.insert(0, '%s: 1-8' % (pfid, ))

        # classification
        showevs = ' '.join(eventlist)
        places = '; '.join(placeslist)
        pev = meet.edb.add_empty(evno=catcomp, notify=True)
        pev.set_values({
            'series': series,
            'type handler': 'classification',
            'prefix': prefix,
            'result': True,
            'index': False,
            'program': False,
            'depends': showevs,
            'auto': places,
            'category': cat,
            'competion': code,
        })
        c = meet.get_event(catcomp)
        c.readonly = False
        c.loadconfig()
        if otherslist:
            c.others = '; '.join(otherslist)
        if othersrc:
            c.othersrc = othersrc
        if domedals:
            c.medals = 'Gold Silver Bronze'
        c.showevents = showevs
        c.saveconfig()
        c = None
    else:
        # straight final, 1-up
        pev = meet.edb.add_empty(evno=catcomp, notify=True)
        pev.set_values({
            'series': series,
            'type handler': 'indiv tt',
            'prefix': prefix,
            'info': 'Final',
            'result': True,
            'index': True,
            'program': True,
            'laps': laps,
            'distance': distance,
            'category': cat,
            'competion': code,
            'phase': 'final',
        })
        c = meet.get_event(catcomp)
        c.readonly = False
        c.loadconfig()
        c.timetype = 'single'
        c.saveconfig()
        c = None


def about_dlg(window, version=None):
    """Display shared about dialog."""
    modal = window is not None
    dlg = Gtk.AboutDialog(modal=modal, destroy_with_parent=True)
    dlg.set_logo_icon_name(metarace.ICON)
    dlg.set_transient_for(window)
    dlg.set_program_name('trackmeet')
    vtxt = 'Library: ' + metarace.__version__
    if version:
        vtxt = 'Application: ' + version + '; ' + vtxt
    dlg.set_version(vtxt)
    dlg.set_copyright('Copyright \u00a9 2012-2025 ndf-zz and contributors')
    dlg.set_comments('Track cycle race result handler')
    dlg.set_license_type(Gtk.License.MIT_X11)
    dlg.set_license(metarace.LICENSETEXT)
    dlg.set_wrap_license(True)
    # if running from an installer venv, enable the update button
    if sys.prefix != sys.base_prefix:
        dlg.add_button("Update", 5)
    response = dlg.run()
    dlg.hide()
    dlg.destroy()
    if response == 5:
        _log.debug('Check for updates...')
        GLib.idle_add(do_update_check, window)
    return None


def chooseFolder(title='',
                 mode=Gtk.FileChooserAction.SELECT_FOLDER,
                 parent=None,
                 path=None):
    ret = None
    modal = parent is not None
    dlg = Gtk.FileChooserNative(title=title, modal=modal)
    dlg.set_transient_for(parent)
    dlg.set_action(mode)
    if path is not None:
        dlg.set_current_folder(path)
    response = dlg.run()
    if response == Gtk.ResponseType.ACCEPT:
        ret = dlg.get_filename()
    _log.debug('Open folder returns: %r (%r)', ret, response)
    dlg.destroy()
    return ret


def chooseCsvFile(title='',
                  mode=Gtk.FileChooserAction.OPEN,
                  parent=None,
                  path=None,
                  hintfile=None):
    ret = None
    modal = parent is not None
    dlg = Gtk.FileChooserNative(title=title, modal=modal)
    dlg.set_transient_for(parent)
    dlg.set_action(mode)
    cfilt = Gtk.FileFilter()
    cfilt.set_name('CSV Files')
    cfilt.add_mime_type('text/csv')
    cfilt.add_pattern('*.csv')
    dlg.add_filter(cfilt)
    cfilt = Gtk.FileFilter()
    cfilt.set_name('All Files')
    cfilt.add_pattern('*')
    dlg.add_filter(cfilt)
    if path is not None:
        dlg.set_current_folder(path)
    if hintfile:
        dlg.set_current_name(hintfile)
    response = dlg.run()
    if response == Gtk.ResponseType.ACCEPT:
        ret = dlg.get_filename()
    dlg.destroy()
    return ret


def mkviewcoltod(view=None,
                 header='',
                 cb=None,
                 width=120,
                 editcb=None,
                 colno=None,
                 style=None):
    """Return a Time of Day view column."""
    i = Gtk.CellRendererText()
    i.set_property('xalign', 1.0)
    j = Gtk.TreeViewColumn(header, i)
    j.set_cell_data_func(i, cb, colno)
    if editcb is not None:
        i.set_property('editable', True)
        i.connect('edited', editcb, colno)
    j.set_min_width(width)
    if style is not None:
        j.add_attribute(i, 'style', style)
    view.append_column(j)
    return j


def mkviewcoltxt(view=None,
                 header='',
                 colno=None,
                 cb=None,
                 width=None,
                 halign=None,
                 calign=None,
                 expand=False,
                 editcb=None,
                 maxwidth=None,
                 minwidth=None,
                 charwidth=None,
                 bgcol=None,
                 style=None,
                 fontdesc=None,
                 wrap=None,
                 fixed=False,
                 valign=None):
    """Return a text view column."""
    i = Gtk.CellRendererText()
    if cb is not None:
        i.set_property('editable', True)
        i.connect('edited', cb, colno)
    if calign is not None:
        i.set_property('xalign', calign)
    if valign is not None:
        i.set_property('yalign', valign)
    if fontdesc is not None:
        i.set_property('font_desc', fontdesc)
    if charwidth is not None:
        i.set_property('width_chars', charwidth)
    if wrap is not None:
        if minwidth is None:
            minwidth = 400
        if wrap:
            i.set_property('wrap-mode', Pango.WrapMode.WORD_CHAR)
            i.set_property('wrap-width', minwidth)
        else:
            i.set_property('wrap-width', -1)

    j = Gtk.TreeViewColumn(header, i, text=colno)
    if bgcol is not None:
        j.add_attribute(i, 'background', bgcol)
    if style is not None:
        j.add_attribute(i, 'style', style)
    if halign is not None:
        j.set_alignment(halign)
    if fixed:
        j.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
    if expand:
        if width is not None:
            j.set_min_width(width)
        j.set_expand(True)
    else:
        if width is not None:
            j.set_min_width(width)
    if maxwidth is not None and wrap is None:
        j.set_max_width(maxwidth)
    view.append_column(j)
    if editcb is not None:
        i.connect('editing-started', editcb)
    return i


def mkviewcolbg(view=None,
                header='',
                colno=None,
                cb=None,
                width=None,
                halign=None,
                calign=None,
                expand=False,
                editcb=None,
                maxwidth=None):
    """Return a text view column."""
    i = Gtk.CellRendererText()
    if cb is not None:
        i.set_property('editable', True)
        i.connect('edited', cb, colno)
    if calign is not None:
        i.set_property('xalign', calign)
    j = Gtk.TreeViewColumn(header, i, background=colno)
    if halign is not None:
        j.set_alignment(halign)
    if expand:
        if width is not None:
            j.set_min_width(width)
        j.set_expand(True)
    else:
        if width is not None:
            j.set_min_width(width)
    if maxwidth is not None:
        j.set_max_width(maxwidth)
    view.append_column(j)
    if editcb is not None:
        i.connect('editing-started', editcb)
    return i


def mkviewcolbool(view=None,
                  header='',
                  colno=None,
                  cb=None,
                  width=None,
                  expand=False):
    """Return a boolean view column."""
    i = Gtk.CellRendererToggle()
    i.set_property('activatable', True)
    if cb is not None:
        i.connect('toggled', cb, colno)
    j = Gtk.TreeViewColumn(header, i, active=colno)
    if expand:
        j.set_min_width(width)
        j.set_expand(True)
    else:
        if width is not None:
            j.set_min_width(width)
    view.append_column(j)
    return i


def coltxtbibser(col, cr, model, iter, data):
    """Display a bib.ser string in a tree view."""
    (bibcol, sercol) = data
    cr.set_property(
        'text',
        strops.bibser2bibstr(model.get_value(iter, bibcol),
                             model.get_value(iter, sercol)))


def mkviewcolbibser(view=None,
                    header='No.',
                    bibcol=0,
                    sercol=1,
                    width=None,
                    expand=False):
    """Return a column to display bib/series as a bib.ser string."""
    i = Gtk.CellRendererText()
    i.set_property('xalign', 1.0)
    j = Gtk.TreeViewColumn(header, i)
    j.set_cell_data_func(i, coltxtbibser, (bibcol, sercol))
    if expand:
        j.set_min_width(width)
        j.set_expand(True)
    else:
        if width is not None:
            j.set_min_width(width)
    view.append_column(j)
    return i


def messagedlg(window=None,
               message='Message',
               message_type=Gtk.MessageType.ERROR,
               buttons=Gtk.ButtonsType.CLOSE,
               subtext=None,
               title=None):
    """Display a message dialog."""
    modal = window is not None
    dlg = Gtk.MessageDialog(modal=modal,
                            message_type=message_type,
                            buttons=buttons,
                            text=message,
                            destroy_with_parent=True)
    dlg.set_transient_for(window)
    if title:
        dlg.set_title(title)
    if subtext is not None:
        dlg.format_secondary_text(subtext)
    ret = False
    response = dlg.run()
    dlg.hide()
    if response == Gtk.ResponseType.OK:
        ret = True
    dlg.destroy()
    return ret


def questiondlg(window=None, question='Question?', subtext=None, title=None):
    """Display a question dialog and return True/False."""
    return messagedlg(window=window,
                      message=question,
                      message_type=Gtk.MessageType.QUESTION,
                      buttons=Gtk.ButtonsType.OK_CANCEL,
                      subtext=subtext,
                      title=title)


class option:
    """Base class for configuration option"""

    def __init__(self, key, schema, obj=None, section=None):
        self.key = key
        self._obj = obj
        self._section = section
        self._attr = None
        self._value = None
        self._oldvalue = None
        self._default = None
        self._type = 'str'
        self._prompt = None
        self._hint = None
        self._subtext = None
        self._control = None
        self._options = {}
        self._places = 0
        self._nowbut = False
        self._readonly = False
        self._defer = False

        # import schema
        if 'type' in schema:
            self._type = schema['type']
        if obj is not None:
            if isinstance(self._obj, config):
                self._attr = key
            elif 'attr' in schema:
                if isinstance(self._obj, (rider, dict, Event)):
                    self._attr = schema['attr']
                else:
                    if schema['attr'] is not None and hasattr(
                            self._obj, schema['attr']):
                        self._attr = schema['attr']
        if 'default' in schema:
            self._default = schema['default']
        if 'value' in schema:
            self._value = schema['value']
        if self._attr is not None and self._value is None:
            if isinstance(self._obj, (rider, Event)):
                self._value = self._obj[self._attr]
            elif isinstance(self._obj, config):
                self._value = self._obj.get_value(self._section, self._attr)
            elif isinstance(self._obj, dict):
                if self._attr in self._obj:
                    valid, value = self.parse_value(self._obj[self._attr])
                    if valid:
                        self._value = value
            else:
                self._value = getattr(self._obj, self._attr)
        self._oldvalue = self._value
        if 'prompt' in schema:
            self._prompt = schema['prompt']
        else:
            self._prompt = key
        if 'hint' in schema:
            self._hint = schema['hint']
        if 'subtext' in schema:
            self._subtext = schema['subtext']
        if 'places' in schema:
            self._places = strops.confopt_posint(schema['places'], 0)
        if 'readonly' in schema:
            self._readonly = bool(schema['readonly'])
        if 'nowbut' in schema:
            self._nowbut = bool(schema['nowbut'])
        if 'defer' in schema:
            self._defer = bool(schema['defer'])
        if 'options' in schema:
            if isinstance(schema['options'], dict):
                self._options[''] = '[Not set]'
                for kv in schema['options']:
                    k = str(kv)
                    v = schema['options'][kv]
                    self._options[k] = v

    def changed(self):
        """Return true if current value differ from original"""
        return self._value != self._oldvalue

    def get_prev(self):
        """Return original option value"""
        return self._oldvalue

    def get_value(self):
        """Return the option's current value"""
        return self._value

    def reset(self):
        self.set_value(self._oldvalue)

    def validate(self):
        """Check proposed value in control"""
        return self.read_value(self._control.get_text())

    def parse_value(self, newtext):
        """Return a value of the correct type for this option"""
        ret = False
        newval = None
        if self._type == 'tod':
            if newtext:
                newval = tod.mktod(newtext)
                if newval is not None:
                    ret = True
            else:
                ret = True
        elif self._type == 'date':
            if newtext:
                newval = strops.confopt_date(newtext)
                if newval is not None:
                    ret = True
            else:
                ret = True
        elif self._type == 'int':
            if newtext is not None and newtext != '':
                newval = strops.confopt_int(newtext)
                if newval is not None:
                    ret = True
            else:
                ret = True
        elif self._type == 'bool':
            newval = strops.confopt_bool(newtext)
            ret = True
        elif self._type == 'chan':
            if newtext:
                newval = strops.confopt_chan(newtext)
                if newval != strops.CHAN_UNKNOWN:
                    ret = True
            else:
                ret = True
        elif self._type == 'float':
            if newtext:
                newval = strops.confopt_float(newtext)
                if newval is not None:
                    ret = True
            else:
                ret = True
        elif self._type == 'str':
            if newtext is not None:
                newval = str(newtext)
                if not newval:
                    # Allow unset of values without default
                    if self._default is None:
                        newval = None
            ret = True
        else:
            _log.warning('Unknown option value type %r=%r', self._type,
                         newtext)
            newval = newtext
            ret = True
        return ret, newval

    def read_value(self, newtext):
        """Try to read and update value from newtext"""
        ret, newval = self.parse_value(newtext)
        if ret:
            self.set_value(newval)
        return ret

    def format_value(self):
        """Return a string for use in a text entry"""
        ret = ''
        if self._value is not None:
            if self._type == 'tod':
                if self._value is not None:
                    prec = min(self._places, self._value.precision())
                    ret = self._value.rawtime(places=prec)
            elif self._type == 'date':
                if self._value is not None:
                    ret = self._value.isoformat()
            else:
                ret = str(self._value)
        return ret

    def set_value(self, newval):
        """Store new value in object and update obj if provided"""
        self._value = newval
        if self._obj is not None and self._attr is not None:
            if isinstance(self._obj, (rider, Event)):
                # Don't trigger notify in this path - leave that to the caller
                self._obj.set_value(self._attr, self._value)
            elif isinstance(self._obj, config):
                self._obj.set(self._section, self._attr, self._value)
            elif isinstance(self._obj, dict):
                self._obj[self._attr] = self._value
            else:
                # assume object.attribute
                setattr(self._obj, self._attr, self._value)
        if self.changed():
            _log.debug('Option %r update value: %r=>%r (%s)', self.key,
                       self._oldvalue, self._value,
                       self._value.__class__.__name__)
        return True

    def _updated(self, control):
        """Handle update event on control"""
        if self.read_value(control.get_text()):
            control.set_text(self.format_value())
            return True
        else:
            return False

    def _prompt_label(self):
        """Return a prompt label"""
        lbl = Gtk.Label(label=self._prompt)
        lbl.set_single_line_mode(True)
        lbl.set_halign(Gtk.Align.START)
        lbl.show()
        return lbl

    def add_control(self, grid, row):
        """Create a new control and add it to the provided grid"""
        grid.attach(self._prompt_label(), 0, row, 1, 1)

        self._control = Gtk.Entry()
        self._control.set_width_chars(32)
        self._control.set_activates_default(True)
        if self._value is not None:
            self._control.set_text(self.format_value())
        if self._hint is not None:
            self._control.set_tooltip_text(self._hint)
        self._control.show()
        if not self._defer:
            self._control.connect('activate', self._updated)
        if self._readonly:
            self._control.set_editable(False)
        grid.attach(self._control, 1, row, 4, 1)
        return 1


class optionShort(option):

    def _now_press(self, widget, evt):
        """Transfer now into value and re-validate"""
        self._value = tod.now().truncate(self._places)
        self._control.set_text(self.format_value())

    def add_control(self, grid, row):
        """Create a new control and add it to the provided grid"""
        grid.attach(self._prompt_label(), 0, row, 1, 1)

        self._control = Gtk.Entry()
        self._control.set_width_chars(12)
        self._control.set_activates_default(True)
        if self._value is not None:
            self._control.set_text(self.format_value())
        if self._hint is not None:
            self._control.set_tooltip_text(self._hint)
        self._control.show()
        if not self._defer:
            self._control.connect('activate', self._updated)
        if self._readonly:
            self._control.set_editable(False)
        grid.attach(self._control, 1, row, 1, 1)

        if self._nowbut:
            but = Gtk.Button()
            but.set_label('Now')
            but.set_halign(Gtk.Align.START)
            but.set_can_focus(False)
            but.show()
            if self._subtext:
                but.set_tooltip_text(self._subtext)
            else:
                but.set_tooltip_text('Set the tod entry to now')
            but.connect('button-press-event', self._now_press)
            grid.attach(but, 2, row, 1, 1)
        else:
            subtext = ''
            if self._subtext:
                subtext = self._subtext
            lbl = Gtk.Label(label=subtext)
            lbl.set_single_line_mode(True)
            lbl.set_halign(Gtk.Align.START)
            lbl.show()
            grid.attach(lbl, 2, row, 3, 1)
        return 1


class optionCheck(option):

    def validate(self):
        """Check proposed value in control"""
        return self.read_value(self._control.get_active())

    def _updated(self, control):
        """Handle update event on control"""
        return self.read_value(self._control.get_active())

    def add_control(self, grid, row):
        """Create a new control and add it to the provided grid"""
        grid.attach(self._prompt_label(), 0, row, 1, 1)

        st = ''
        if self._subtext:
            st = self._subtext
        self._control = Gtk.CheckButton.new_with_label(st)
        if self._value:
            self._control.set_active(True)
        if self._hint is not None:
            self._control.set_tooltip_text(self._hint)
        self._control.show()
        if not self._defer:
            self._control.connect('toggled', self._updated)
        if self._readonly:
            self._control.set_sensitive(False)
        grid.attach(self._control, 1, row, 3, 1)
        return 1


class optionHidden(option):
    """Hidden option with value and type"""

    def add_control(self, grid, row):
        return 0

    def validate(self):
        return True


class optionLabel(option):

    def add_control(self, grid, row):
        grid.attach(self._prompt_label(), 0, row, 1, 1)

        self._control = Gtk.Label()
        self._control.set_halign(Gtk.Align.START)
        self._control.set_selectable(True)
        self._control.set_margin_top(4)
        self._control.set_margin_bottom(4)
        if self._value is not None:
            self._control.set_text(self.format_value())
        if self._hint is not None:
            self._control.set_tooltip_text(self._hint)
        self._control.show()
        grid.attach(self._control, 1, row, 4, 1)
        return 1

    def validate(self):
        return True


class optionChoice(option):

    def validate(self):
        """Check proposed value in control"""
        newval = self._control.get_active_id()
        if newval == '':
            # Allow un-set of option value
            newval = None
        return self.read_value(newval)

    def _updated(self, control):
        """Handle update event on control"""
        return self.validate()

    def add_control(self, grid, row):
        """Create a new control and add it to the provided grid"""
        grid.attach(self._prompt_label(), 0, row, 1, 1)

        self._control = Gtk.ComboBoxText.new()
        for k in self._options:
            self._control.append(k, self._options[k])
        if self._value is not None:
            self._control.set_active_id(self.format_value())
        else:
            self._control.set_active_id('')
        self._control.show()
        if not self._defer:
            self._control.connect('changed', self._updated)
        if self._readonly:
            self._control.set_sensitive(False)
        if self._hint is not None:
            self._control.set_tooltip_text(self._hint)
        grid.attach(self._control, 1, row, 3, 1)

        subtext = ''
        if self._subtext:
            subtext = self._subtext
        lbl = Gtk.Label(label=subtext)
        lbl.set_single_line_mode(True)
        lbl.show()
        grid.attach(lbl, 4, row, 1, 1)

        return 1


class optionSection(option):

    def validate(self):
        return True

    def add_control(self, grid, row):
        """Create a new control and add it to the provided grid"""
        lbl = Gtk.Label(label=self._prompt)
        lbl.set_single_line_mode(True)
        lbl.set_halign(Gtk.Align.START)
        if hasattr(Pango.AttrList, 'from_string'):
            lbl.set_attributes(Pango.AttrList.from_string('0 -1 style italic'))
        if row != 0:
            lbl.set_margin_top(15)
        lbl.show()
        grid.attach(lbl, 0, row, 5, 1)
        return 1


def get_monitor_height(widget=None):
    """Return the monitor height"""
    monitor = None
    display = Gdk.Display.get_default()

    if widget is not None:
        # use widget to select monitor
        window = widget.get_window()
        monitor = display.get_monitor_at_window(window)
    else:
        # try using pointer to find monitor
        x = 0
        y = 0
        with suppress(Exception):
            seat = display.get_default_seat()
            pointer = seat.get_pointer()
            position = pointer.get_position()
            x = position.x
            y = position.y
        _log.debug('Looking for a monitor near [%d, %d]', x, y)
        monitor = display.get_monitor_at_point(x, y)

    geometry = monitor.get_geometry()
    return monitor.get_geometry().height


def options_dlg(window=None, title='Options', sections={}, action=False):
    """Build and display an option editor for the provided sections

      sections={
        "section": {
          "object": OBJECT, rider, event or section
          "title": section label
          "schema": {
            "key": {
              "value": [Original value],
              "control": [Control type],
              "type" : [Value type],
              "prompt": [Prompt text],
              "subtext": [Extra info],
              "hint": [Tooltip],
              "places": [Decimal places for tod value],
              "attr": [Attribute in optional obj for direct edit],
              "options": { "key":"Text", ... },
            },
            ...
          }

       Value types:

         str: text string
         int: integer value
         float: floating point number
         chan: timing channel
         bool: True/False
         tod: Time of day object with number of places in schema
         date: datetime.date object

       Control types:

         none: nothing displayed for the config option
         label: prompt and value as readonly text
         section: section delimiter
         text: standard text input
         short: short text input, extra info displayed right of input
         check: on/off selection, extra info displayed right of input
         choice: select box, choice of options provided in schema

    Return value is a dict of dicts with one tuple per key:

        "section": {"key": (changed, oldval, newval), ...}, ...

    If action is True, OK/Cancel status is returned in res['action']

    Note: section controls return (False, None, None)
    """
    omap = {}
    # read schema into options map
    for sec in sections:
        omap[sec] = {'title': sections[sec]['title'], 'options': {}}
        for key in sections[sec]['schema']:
            oschema = sections[sec]['schema'][key]
            obj = sections[sec]['object']
            otype = 'text'
            if 'control' in oschema:
                otype = oschema['control']
            if otype == 'section':
                omap[sec]['options'][key] = optionSection(
                    key, oschema, obj, sec)
            elif otype == 'short':
                omap[sec]['options'][key] = optionShort(key, oschema, obj, sec)
            elif otype == 'check':
                omap[sec]['options'][key] = optionCheck(key, oschema, obj, sec)
            elif otype == 'label':
                omap[sec]['options'][key] = optionLabel(key, oschema, obj, sec)
            elif otype == 'choice':
                omap[sec]['options'][key] = optionChoice(
                    key, oschema, obj, sec)
            elif otype == 'none':
                omap[sec]['options'][key] = optionHidden(
                    key, oschema, obj, sec)
            else:
                omap[sec]['options'][key] = option(key, oschema, obj, sec)

    # build dialog
    modal = window is not None
    max_height = MAX_HEIGHT_FACTOR * get_monitor_height(window)
    dlg = Gtk.Dialog(title=title, modal=modal, destroy_with_parent=True)
    dlg.set_transient_for(window)
    geom = Gdk.Geometry()
    geom.max_height = int(max(MAX_HEIGHT_MIN, max_height))
    geom.max_width = -1
    _log.debug('Set dialog max height hint to: %d', geom.max_height)
    dlg.set_geometry_hints(None, geom, Gdk.WindowHints.MAX_SIZE)
    dlg.add_buttons("Cancel", 2, "OK", 0)
    dlg.set_default_response(0)

    # container type depends on number of config sections
    ctr = None
    onePage = False
    if len(omap) == 1:
        ctr = Gtk.ScrolledWindow()
        ctr.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        ctr.set_propagate_natural_height(True)
        onePage = True
    else:
        ctr = Gtk.Notebook()
        ctr.set_tab_pos(Gtk.PositionType.LEFT)
    ctr.show()
    dlg.get_content_area().pack_start(ctr, True, True, 0)

    for section in omap:
        grid = Gtk.Grid()
        grid.props.margin = 8
        grid.set_row_spacing(4)
        grid.set_column_spacing(8)
        grid.set_column_homogeneous(False)
        grid.set_row_homogeneous(False)
        row = 0
        for key in omap[section]['options']:
            rows = omap[section]['options'][key].add_control(grid, row)
            row += rows
        grid.show()
        if onePage:
            ctr.add(grid)
        else:
            scr = Gtk.ScrolledWindow()
            scr.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scr.set_propagate_natural_height(True)
            scr.add(grid)
            scr.show()
            l = Gtk.Label()
            l.set_text(omap[section]['title'])
            l.set_width_chars(12)
            l.show()
            ctr.append_page(scr, l)

    retval = dlg.run()
    dlg.hide()

    # change report
    res = {}
    if retval != 0:  # escape/cancel
        # reset all values and report no changes
        for section in omap:
            res[section] = {}
            sec = omap[section]['options']
            for key in sec:
                o = sec[key]
                o.reset()
                res[section][key] = (False, o.get_prev(), o.get_prev())
    else:
        # re-validate all entries and report changes
        for section in omap:
            res[section] = {}
            sec = omap[section]['options']
            for key in sec:
                o = sec[key]
                if not o.validate():
                    _log.warning('Invalid value for option %r ignored', key)
                res[section][key] = (o.changed(), o.get_prev(), o.get_value())
    if action:
        res['action'] = retval

    dlg.destroy()
    return res


class decisionEditor:

    def __init__(self, window=None, decisions=[]):
        modal = window is not None
        self._dlg = Gtk.Dialog(
            title="Edit Decisions of the Commissaires Panel",
            modal=modal,
            destroy_with_parent=True)
        self._dlg.set_transient_for(window)
        self._dlg.add_buttons("Done", 0)

        self._model = Gtk.ListStore(str, str)
        for d in decisions:
            self._model.append((
                '\u2023',
                d.strip(),
            ))
        self._view = Gtk.TreeView(self._model)
        self._view.set_reorderable(True)
        self._view.set_rules_hint(False)
        self._view.set_headers_visible(False)
        self._view.set_property('height-request', 200)
        mkviewcoltxt(self._view, 'Bullet', 0, charwidth=2, valign=0.0)
        mkviewcoltxt(self._view,
                     'Decision',
                     1,
                     expand=True,
                     width=400,
                     charwidth=66,
                     cb=self.edit_decision,
                     wrap=True,
                     valign=0.0)
        self._view.show()
        ctr = Gtk.ScrolledWindow()
        ctr.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        ctr.set_propagate_natural_height(True)
        ctr.add(self._view)
        ctr.show()
        self._dlg.get_content_area().pack_start(ctr, True, True, 4)
        bb = Gtk.ButtonBox()
        bb.set_layout(Gtk.ButtonBoxStyle.START)
        bb.show()

        but = Gtk.Button.new_from_icon_name('list-add-symbolic',
                                            Gtk.IconSize.LARGE_TOOLBAR)
        but.set_always_show_image(True)
        but.show()
        but.connect('clicked', self.add_empty)
        bb.pack_start(but, False, False, 0)
        bb.set_child_non_homogeneous(but, True)

        but = Gtk.Button.new_from_icon_name('list-remove-symbolic',
                                            Gtk.IconSize.LARGE_TOOLBAR)
        but.set_always_show_image(True)
        but.show()
        but.connect('clicked', self.del_selected)
        bb.pack_start(but, False, False, 0)
        bb.set_child_non_homogeneous(but, True)

        but = Gtk.Button.new_from_icon_name('pan-up-symbolic',
                                            Gtk.IconSize.LARGE_TOOLBAR)
        but.set_always_show_image(True)
        but.show()
        but.connect('clicked', self.move_up)
        bb.pack_start(but, False, False, 0)
        bb.set_child_non_homogeneous(but, True)

        but = Gtk.Button.new_from_icon_name('pan-down-symbolic',
                                            Gtk.IconSize.LARGE_TOOLBAR)
        but.set_always_show_image(True)
        but.show()
        but.connect('clicked', self.move_down)
        bb.pack_start(but, False, False, 0)
        bb.set_child_non_homogeneous(but, True)

        self._dlg.get_content_area().pack_start(bb, False, False, 4)

    def del_selected(self, button):
        """Delete the selected row."""
        model, i = self._view.get_selection().get_selected()
        if i is not None:
            self._model.remove(i)

    def move_up(self, button):
        """Move selected row up one slot"""
        model, i = self._view.get_selection().get_selected()
        if i is not None:
            j = self._model.iter_previous(i)
            if j is not None:
                self._model.swap(i, j)

    def move_down(self, button):
        """Move selected row down one slot"""
        model, i = self._view.get_selection().get_selected()
        if i is not None:
            j = self._model.iter_next(i)
            if j is not None:
                self._model.swap(i, j)

    def add_empty(self, button):
        """Add an empty row and trigger editing the content"""
        i = self._model.append(('\u2023', ''))
        path = Gtk.TreeModelRow(self._model, i).path
        self._view.set_cursor(path, self._view.get_column(1), True)

    def edit_decision(self, cell, path, new_text, col):
        """Edit column callback."""
        new_text = new_text.strip()
        self._model[path][col] = new_text

    def run(self):
        # for now, ignore dialog return value
        self._dlg.run()
        self._dlg.hide()
        res = [d[1] for d in self._model]
        self._dlg.destroy()
        return res


def decisions_dlg(window=None, decisions=[]):
    """Edit decisions of the commissaires panel and return an updated list"""
    dlg = decisionEditor(window=window, decisions=decisions)
    return dlg.run()
