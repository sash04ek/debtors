"""Системный выбор даты. В Tk нет встроенного элемента выбора даты, поэтому стандартный календарь операционной системы
показывается отдельным системным окном, которое запускается вспомогательным процессом:
- macOS — стандартный NSDatePicker (календарь) во всплывающей панели под полем, через osascript (JavaScript for Automation);
- Windows — стандартный календарь MonthCalendar (Windows Forms) в диалоге PowerShell.
На других системах и при любой неудаче используется календарь самой программы (datepicker.CalendarPopup).
Результат процесса — одна строка: «OK:гггг-мм-дд», «CLEAR» или «CANCEL»."""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from datetime import date, datetime

MAC_SCRIPT = r"""
ObjC.import('AppKit');
function run(argv) {
  var initial = argv[0] || '', allowClear = argv[1] === '1', x = parseFloat(argv[2] || '400'), yBelow = parseFloat(argv[3] || '300'), yAbove = parseFloat(argv[4] || '300'), auto = argv[5] || '', look = argv[6] || '';
  var app = $.NSApplication.sharedApplication;
  app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
  var f = $.NSDateFormatter.alloc.init; f.dateFormat = 'yyyy-MM-dd';
  var state = {result: 'CANCEL'};
  var picker = $.NSDatePicker.alloc.initWithFrame($.NSMakeRect(0, 0, 10, 10));
  picker.datePickerStyle = 1; picker.datePickerElements = 224; picker.focusRingType = 1;
  picker.dateValue = (initial ? f.dateFromString(initial) : null) || $.NSDate.date;
  picker.sizeToFit;
  var pw = picker.frame.size.width, ph = picker.frame.size.height;
  var pad = 10, footer = allowClear ? 30 : 0;
  var W = pw + 2 * pad, H = ph + 2 * pad + footer;
  var screenH = $.NSScreen.screens.objectAtIndex(0).frame.size.height, screenW = $.NSScreen.screens.objectAtIndex(0).frame.size.width;
  var y = (yBelow + H > screenH - 40) ? Math.max(0, yAbove - H - 4) : yBelow;
  x = Math.max(0, Math.min(x, screenW - W));
  ObjC.registerSubclass({name: 'DPPanel', superclass: 'NSPanel', methods: {
    'canBecomeKeyWindow': {types: ['char', []], implementation: function () { return true; }},
    'cancelOperation:': {types: ['void', ['id']], implementation: function (s) { app.stopModal; }}
  }});
  var panel = $.DPPanel.alloc.initWithContentRectStyleMaskBackingDefer($.NSMakeRect(x, screenH - y - H, W, H), $.NSWindowStyleMaskBorderless, 2, false);
  if (look) panel.appearance = $.NSAppearance.appearanceNamed(look === 'dark' ? 'NSAppearanceNameDarkAqua' : 'NSAppearanceNameAqua');
  panel.opaque = false; panel.backgroundColor = $.NSColor.clearColor; panel.level = 3; panel.hasShadow = true;
  var fx = $.NSVisualEffectView.alloc.initWithFrame($.NSMakeRect(0, 0, W, H));
  fx.material = 6; fx.blendingMode = 0; fx.state = 1; fx.wantsLayer = true; fx.layer.cornerRadius = 10; fx.layer.masksToBounds = true;
  panel.contentView = fx;
  picker.setFrameOrigin($.NSMakePoint(pad, pad + footer));
  fx.addSubview(picker);
  ObjC.registerSubclass({name: 'DPTarget', methods: {
    'picked:': {types: ['void', ['id']], implementation: function (s) { state.result = 'OK:' + ObjC.unwrap(f.stringFromDate(picker.dateValue)); app.stopModal; }},
    'cleared:': {types: ['void', ['id']], implementation: function (s) { state.result = 'CLEAR'; app.stopModal; }},
    'windowDidResignKey:': {types: ['void', ['id']], implementation: function (n) { app.stopModal; }}
  }});
  var tgt = $.DPTarget.alloc.init;
  picker.target = tgt; picker.action = 'picked:';
  panel.delegate = tgt;
  if (allowClear) {
    var b = $.NSButton.alloc.initWithFrame($.NSMakeRect(pad, 6, W - 2 * pad, 22));
    b.title = 'Очистить'; b.bezelStyle = 1; b.controlSize = 1; b.font = $.NSFont.systemFontOfSize(11); b.target = tgt; b.action = 'cleared:';
    fx.addSubview(b);
  }
  if (auto) {
    ObjC.registerSubclass({name: 'DPAuto', methods: {'tick:': {types: ['void', ['id']], implementation: function (t) {
      if (auto === 'clear') { state.result = 'CLEAR'; } else { state.result = 'OK:' + ObjC.unwrap(f.stringFromDate(picker.dateValue)); }
      app.stopModal; }}}});
    var timer = $.NSTimer.timerWithTimeIntervalTargetSelectorUserInfoRepeats(1.5, $.DPAuto.alloc.init, 'tick:', $(), false);
    $.NSRunLoop.mainRunLoop.addTimerForMode(timer, $.NSRunLoopCommonModes);
  }
  app.activateIgnoringOtherApps(true);
  panel.makeKeyAndOrderFront($());
  app.runModalForWindow(panel);
  panel.orderOut($());
  return state.result;
}
"""

_WIN_TEMPLATE = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$inv = [System.Globalization.CultureInfo]::InvariantCulture
$form = New-Object System.Windows.Forms.Form
$form.Text = '{title}'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.ShowInTaskbar = $false
$form.TopMost = $true
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point({x}, {y})
$cal = New-Object System.Windows.Forms.MonthCalendar
$cal.MaxSelectionCount = 1
$cal.Location = New-Object System.Drawing.Point(10, 10)
{set_date}
$form.Controls.Add($cal)
$form.ClientSize = New-Object System.Drawing.Size(($cal.Width + 20), ($cal.Height + 56))
$script:result = 'CANCEL'
function Pick() {{ $script:result = 'OK:' + $cal.SelectionStart.ToString('yyyy-MM-dd', $inv); $form.Close() }}
$by = $cal.Height + 18
$ok = New-Object System.Windows.Forms.Button
$ok.Text = 'Выбрать'; $ok.Size = New-Object System.Drawing.Size(72, 26); $ok.Location = New-Object System.Drawing.Point(10, $by)
$ok.Add_Click({{ Pick }})
$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = 'Отмена'; $cancel.Size = New-Object System.Drawing.Size(72, 26); $cancel.Location = New-Object System.Drawing.Point(88, $by)
$cancel.Add_Click({{ $form.Close() }})
$form.Controls.Add($ok); $form.Controls.Add($cancel)
{clear_button}
$cal.Add_DateSelected({{ Pick }})
$form.AcceptButton = $ok
$form.CancelButton = $cancel
[void]$form.ShowDialog()
Write-Output $script:result
"""

_WIN_CLEAR = r"""$clear = New-Object System.Windows.Forms.Button
$clear.Text = 'Очистить'; $clear.Size = New-Object System.Drawing.Size(72, 26); $clear.Location = New-Object System.Drawing.Point(166, $by)
$clear.Add_Click({ $script:result = 'CLEAR'; $form.Close() })
$form.Controls.Add($clear)"""


def available() -> bool:
    """Есть ли на этом компьютере системный выбор даты (macOS с osascript или Windows с PowerShell)."""
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None
    if sys.platform.startswith("win"):
        return shutil.which("powershell") is not None
    return False


def windows_script(initial: str, allow_clear: bool, title: str, x: int, y: int) -> str:
    safe = lambda s: str(s).replace("'", "''")
    set_date = (f"$cal.SetDate([datetime]::ParseExact('{safe(initial)}', 'yyyy-MM-dd', $inv))" if initial else "")
    return _WIN_TEMPLATE.format(title=safe(title), x=int(x), y=int(y), set_date=set_date,
                                clear_button=_WIN_CLEAR if allow_clear else "")


def build_command(initial: str, allow_clear: bool, title: str, x: int = 0, y: int = 0, platform: str | None = None,
                  auto: str = "", y_above: int | None = None, look: str = "") -> tuple[list[str], dict]:
    """Команда запуска вспомогательного процесса для текущей (или заданной) платформы и параметры Popen."""
    platform = platform or sys.platform
    if platform == "darwin":
        above = y if y_above is None else y_above
        return (["osascript", "-l", "JavaScript", "-e", MAC_SCRIPT, initial, "1" if allow_clear else "0", str(int(x)), str(int(y)),
                 str(int(above)), auto, look], {})
    if platform.startswith("win"):
        encoded = base64.b64encode(windows_script(initial, allow_clear, title, x, y).encode("utf-16-le")).decode("ascii")
        return (["powershell", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                {"creationflags": 0x08000000})                                    # CREATE_NO_WINDOW: без чёрного окна консоли
    raise OSError("системный выбор даты на этой системе недоступен")


def parse_output(text: str) -> tuple[str, date | None]:
    """«OK:2026-10-09» -> ("pick", дата); «CLEAR» -> ("clear", None); всё остальное — ("cancel", None)."""
    line = (text or "").strip().splitlines()[-1].strip() if (text or "").strip() else ""
    if line.startswith("OK:"):
        try:
            return "pick", datetime.strptime(line[3:].strip(), "%Y-%m-%d").date()
        except ValueError:
            return "cancel", None
    if line == "CLEAR":
        return "clear", None
    return "cancel", None


def ask(widget, current: date | None, allow_clear: bool, title: str, on_result, x: int = 0, y: int = 0, auto: str = "",
        y_above: int | None = None, look: str = "") -> None:
    """Показывает системный календарь, не блокируя интерфейс Tk. on_result(kind, date): kind — pick / clear / cancel / error."""
    cmd, kwargs = build_command(current.strftime("%Y-%m-%d") if current else "", allow_clear, title, x, y, auto=auto, y_above=y_above, look=look)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", **kwargs)
    except OSError:
        on_result("error", None)
        return

    def poll():
        if proc.poll() is None:
            try:
                widget.after(80, poll)
            except Exception:
                proc.kill()                                       # окно закрыли, пока календарь был открыт
            return
        out, _err = proc.communicate()
        if proc.returncode != 0:
            on_result("error", None)
        else:
            kind, d = parse_output(out)
            on_result(kind, d)
    poll()
