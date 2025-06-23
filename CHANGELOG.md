## [Unreleased]

### Added

   - Added topn field for marking qualified riders
   - Recover start impulse enabled for all timed events

### Changed

   - Rider db column names and default order updated
   - Add riders from event db no longer supported
   - Autospec no longer property of event handler, read
     instead from eventdb
   - Allow edit of points race intermediates after race start
   - All handlers can now load and save without UI

### Deprecated

### Removed

   - Add riders from eventdb no longer supported
   - Superfluous JSON exports removed from export and index
   - Startplace offset removed from race handler

### Fixed

   - Fixed GTK segfault from export thread
   - Event and rider change notifications connected to all event handlers
   - Competitor 'club' field fixed in points race startlist

### Security

## [1.13.3] - 2025-06-19

### Added

   - Command line option --create to create and load empty meet
   - Pre-load common omnium options and populate references automatically
   - A5 booklet template for program export
   - Add standard sponsor and prizemoney footers on program reports
   - Include optional list of competitors at start of program

### Changed

   - Launch without meet path opens a path chooser dialog
   - Edit dialog height constrained to monitor size
   - Spreadsheet outputs use xlsx format
   - Eventdb moved into trackmeet package
   - Points race allows fractional lap intermediates
   - Suppress team members in program exports
   - List configured competitions separately in index of events

### Deprecated

   - Add riders from eventdb to be removed

### Fixed

   - Repair contest label and intermediate counts in points race
   - Remove silent truncation of prefix and info within event handler UI
