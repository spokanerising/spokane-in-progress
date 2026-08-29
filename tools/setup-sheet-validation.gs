/**
 * Spokane in Progress — sheet guardrails.
 *
 * Run this once from the spreadsheet: Extensions > Apps Script, paste this in,
 * pick setUpValidation from the function dropdown, press Run. Safe to re-run
 * any time; it replaces the rules it set last time rather than stacking them.
 *
 * It does three jobs:
 *
 *   1. Dropdowns, so status and published can only hold values build.py knows.
 *   2. Plain-text formatting on the identifier and date columns. This is the
 *      important one and it is not cosmetic — see the note on parcel_id below.
 *   3. Range checks on the numeric columns, and a highlight on any row the
 *      build will not be able to place on the map.
 *
 * Columns are found by their header name, so reordering them is fine. Any
 * column listed here that is missing from the sheet is skipped quietly.
 */

// Must stay identical to STAGES in build.py.
var STAGES = [
  'Pre-Application',
  'Applied',
  'Approved',
  'Under Construction',
  'Complete',
  'Stalled'
];

// build.py only publishes an image when permission is one of the latter two.
var IMAGE_PERMISSIONS = ['none', 'granted', 'public-record'];

/**
 * Columns stored as literal text.
 *
 * parcel_id is the one that really matters. Left as a number, Sheets treats
 * 36174.1610 as the value 36174.161 and drops the trailing zero, and the
 * county parcel lookup then fails on a number that looks correct on screen.
 * The date columns are here for the same class of reason: as real dates they
 * export to CSV in whatever the locale format is, and the site would start
 * showing "since 8/27/2026" instead of "since 2026-08-27".
 */
var TEXT_COLUMNS = [
  'id',
  'parcel_id',
  'status_updated',
  'last_verified',
  'permit_numbers',
  'drb_file',
  'permit_url',
  'image_url',
  'doc_url',
  'source_urls'
];

var COUNT_COLUMNS = ['units', 'sqft', 'stories', 'parking', 'est_cost'];

function setUpValidation() {
  var sheet = findDataSheet();
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var lastRow = Math.max(sheet.getMaxRows(), 500);
  var bodyRows = lastRow - 1;
  var applied = [];

  function columnOf(name) {
    var index = headers.indexOf(name);
    return index === -1 ? null : index + 1;
  }

  function body(name) {
    var col = columnOf(name);
    return col ? sheet.getRange(2, col, bodyRows, 1) : null;
  }

  function apply(name, rule, note) {
    var range = body(name);
    if (!range) return;
    range.setDataValidation(rule);
    if (note) range.setNote(note);
    applied.push(name);
  }

  // ---- 1. text formatting, before anything else touches these cells -------
  TEXT_COLUMNS.forEach(function (name) {
    var range = body(name);
    if (range) range.setNumberFormat('@');
  });

  // ---- 2. dropdowns ------------------------------------------------------
  apply('status', list(STAGES),
        'One of the six stages. build.py also accepts a few older spellings, ' +
        'but anything it cannot place is shown as Stalled.');

  apply('published', list(['TRUE', 'FALSE']),
        'FALSE keeps the row off the site. Use it while you are still researching.');

  apply('image_permission', list(IMAGE_PERMISSIONS),
        'An image is only published when this is granted or public-record.');

  apply('project_type', SpreadsheetApp.newDataValidation()
        .requireTextIsNotEmpty()
        .setAllowInvalid(true)
        .setHelpText('Free text — Housing, Mixed-use, Office, Middle housing, and so on.')
        .build());

  // ---- 3. dates ----------------------------------------------------------
  ['status_updated', 'last_verified'].forEach(function (name) {
    var col = columnOf(name);
    if (!col) return;
    var a1 = columnLetter(col) + '2';
    apply(name, SpreadsheetApp.newDataValidation()
      .requireFormulaSatisfied('=OR(ISBLANK(' + a1 + '), REGEXMATCH(TO_TEXT(' + a1 + '), "^\\d{4}-\\d{2}-\\d{2}$"))')
      .setAllowInvalid(false)
      .setHelpText('Write the date as 2026-08-27. Other formats change how the site reads it.')
      .build());
  });

  // ---- 4. numbers --------------------------------------------------------
  COUNT_COLUMNS.forEach(function (name) {
    apply(name, SpreadsheetApp.newDataValidation()
      .requireNumberGreaterThanOrEqualTo(0)
      .setAllowInvalid(false)
      .setHelpText('A plain number, or leave it blank. No commas, no $ — build.py adds those.')
      .build());
  });

  // ---- 5. coordinates, now optional --------------------------------------
  bound('lat', 47.60, 47.76,
        'Optional. Leave blank and the build derives it from parcel_id. ' +
        'Fill it in only to override that.');
  bound('lng', -117.58, -117.28,
        'Optional. Leave blank and the build derives it from parcel_id.');

  function bound(name, low, high, note) {
    var col = columnOf(name);
    if (!col) return;
    var a1 = columnLetter(col) + '2';
    apply(name, SpreadsheetApp.newDataValidation()
      .requireFormulaSatisfied('=OR(ISBLANK(' + a1 + '), AND(ISNUMBER(' + a1 + '), ' +
                               a1 + '>=' + low + ', ' + a1 + '<=' + high + '))')
      .setAllowInvalid(false)
      .setHelpText('Outside Spokane. Check for a swapped lat/lng, or leave it blank.')
      .build(), note);
  }

  // ---- 6. header row -----------------------------------------------------
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, headers.length)
       .setFontWeight('bold')
       .setBackground('#f0f0ee');

  // ---- 7. flag rows the build cannot place -------------------------------
  var latCol = columnOf('lat');
  var lngCol = columnOf('lng');
  var parcelCol = columnOf('parcel_id');
  var publishedCol = columnOf('published');
  var rules = sheet.getConditionalFormatRules().filter(function (rule) {
    // drop the rule this script added last time, keep the user's own
    var c = rule.getBooleanCondition();
    return !(c && c.getCriteriaValues()[0] &&
             String(c.getCriteriaValues()[0]).indexOf('SPOKANE_UNLOCATABLE') !== -1);
  });

  if (latCol && lngCol && parcelCol && publishedCol) {
    var formula = '=AND("SPOKANE_UNLOCATABLE"<>"", UPPER(TO_TEXT($' +
      columnLetter(publishedCol) + '2))="TRUE", $' +
      columnLetter(latCol) + '2="", $' +
      columnLetter(lngCol) + '2="", $' +
      columnLetter(parcelCol) + '2="")';
    rules.push(SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied(formula)
      .setBackground('#fce8e6')
      .setRanges([sheet.getRange(2, 1, bodyRows, headers.length)])
      .build());
    sheet.setConditionalFormatRules(rules);
  }

  SpreadsheetApp.getActive().toast(
    'Guardrails applied to: ' + applied.join(', '), 'Spokane in Progress', 8);
}

/** The tab whose header row is the project table, not the form responses. */
function findDataSheet() {
  var sheets = SpreadsheetApp.getActive().getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].getLastColumn() < 2) continue;
    var headers = sheets[i].getRange(1, 1, 1, sheets[i].getLastColumn()).getValues()[0];
    if (headers.indexOf('id') !== -1 && headers.indexOf('published') !== -1) {
      return sheets[i];
    }
  }
  throw new Error('No tab has an "id" and a "published" column in row 1.');
}

function list(values) {
  return SpreadsheetApp.newDataValidation()
    .requireValueInList(values, true)
    .setAllowInvalid(false)
    .build();
}

function columnLetter(index) {
  var letter = '';
  while (index > 0) {
    var remainder = (index - 1) % 26;
    letter = String.fromCharCode(65 + remainder) + letter;
    index = (index - remainder - 1) / 26;
  }
  return letter;
}
