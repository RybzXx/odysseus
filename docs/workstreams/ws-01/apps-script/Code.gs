/**
 * ws-01 D8: liveness checker. Reads heartbeat.json from the same Drive folder
 * the phone uploads to (phone/ws01_heartbeat.sh), and emails an alert the
 * moment any of its three fields goes stale -- distinguishing scheduler-dead,
 * backup-failing, and device-offline, per [LOCKED] L1. Runs entirely on
 * Google's infrastructure, independent of the phone and the laptop (L2).
 *
 * Setup (see ../RUNBOOK.md for the full walkthrough):
 *   1. script.google.com/create -> paste this file in as Code.gs.
 *   2. Set HEARTBEAT_FILE_ID and ALERT_EMAIL below.
 *   3. Triggers (clock icon) -> Add Trigger -> checkHeartbeat -> Time-driven ->
 *      Minutes timer -> Every 15 minutes.
 *   4. Run checkHeartbeat once manually to grant Drive/Mail permissions.
 */

var HEARTBEAT_FILE_ID = 'PASTE_THE_DRIVE_FILE_ID_HERE';
var ALERT_EMAIL = 'PASTE_YOUR_EMAIL_HERE';

// Grace windows, in minutes, before a stale field is treated as a real failure
// rather than an in-flight run. device_online_at and scheduler_tick_at are
// reported every 15 min by ws01_heartbeat.sh; backup_success_at every hour by
// ws01_backup_db.sh -- each grace window is roughly 2x its own reporting cadence.
var GRACE_MINUTES = {
  device_online_at: 30,
  scheduler_tick_at: 30,
  backup_success_at: 150
};

var ALERT_LABEL = {
  device_online_at: 'Device appears OFFLINE',
  scheduler_tick_at: 'Scheduler appears DEAD',
  backup_success_at: 'Backup is FAILING'
};

var RECOVERY_LABEL = {
  device_online_at: 'Device',
  scheduler_tick_at: 'Scheduler',
  backup_success_at: 'Backup'
};

function checkHeartbeat() {
  var props = PropertiesService.getScriptProperties();
  var now = new Date();
  var data;

  try {
    var file = DriveApp.getFileById(HEARTBEAT_FILE_ID);
    data = JSON.parse(file.getBlob().getDataAsString());
  } catch (e) {
    // The heartbeat file itself being unreadable IS a device-offline signal --
    // treat every field as stale rather than silently doing nothing.
    data = {};
  }

  Object.keys(GRACE_MINUTES).forEach(function (field) {
    var raw = data[field];
    var staleKey = 'stale_' + field;
    var wasStale = props.getProperty(staleKey) === 'true';
    var isStale = true;

    if (raw) {
      var ts = new Date(raw);
      var ageMinutes = (now.getTime() - ts.getTime()) / 60000;
      isStale = ageMinutes > GRACE_MINUTES[field];
    }

    if (isStale && !wasStale) {
      sendAlert(field, raw);
      props.setProperty(staleKey, 'true');
    } else if (!isStale && wasStale) {
      sendRecovery(field);
      props.setProperty(staleKey, 'false');
    }
  });
}

function sendAlert(field, lastSeenRaw) {
  var lastSeen = lastSeenRaw || '(never recorded)';
  MailApp.sendEmail(
    ALERT_EMAIL,
    'ws-01 ALERT: ' + ALERT_LABEL[field],
    ALERT_LABEL[field] + '.\nLast known good: ' + lastSeen + '\nChecked at: ' + new Date()
  );
}

function sendRecovery(field) {
  MailApp.sendEmail(
    ALERT_EMAIL,
    'ws-01 RECOVERED: ' + RECOVERY_LABEL[field],
    RECOVERY_LABEL[field] + ' is reporting healthy again as of ' + new Date()
  );
}
