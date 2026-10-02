"""Системный выбор даты. В Tk нет встроенного элемента выбора даты, поэтому стандартный календарь операционной системы
показывается отдельной всплывающей панелью, которую запускает вспомогательный процесс:
- macOS — стандартный NSDatePicker (календарь) в панели под полем, через osascript (JavaScript for Automation);
- Windows — стандартный календарь MonthCalendar (Windows Forms) в панели PowerShell.
Панель не забирает фокус у поля ввода: пока она открыта, дату можно набирать с клавиатуры, а календарь следует за введённым
значением (программа пишет его во временный файл, панель читает). Панель закрывает сама программа (клик вне поля, Esc, Enter,
уход фокуса). На других системах и при любой неудаче используется календарь самой программы (datepicker.CalendarPopup).
Результат процесса — одна строка: «OK:гггг-мм-дд», «CLEAR» или «CANCEL»."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime

MAC_SCRIPT = r"""
ObjC.import('AppKit'); ObjC.import('stdlib');
function run(argv) {
  var initial = argv[0] || '', allowClear = argv[1] === '1', x = parseFloat(argv[2] || '400'), yBelow = parseFloat(argv[3] || '300'),
      yAbove = parseFloat(argv[4] || '300'), auto = argv[5] || '', look = argv[6] || '', syncPath = argv[7] || '';
  var app = $.NSApplication.sharedApplication;
  app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
  var f = $.NSDateFormatter.alloc.init; f.dateFormat = 'yyyy-MM-dd';
  var picker = $.NSDatePicker.alloc.initWithFrame($.NSMakeRect(0, 0, 10, 10));
  picker.datePickerStyle = 1; picker.datePickerElements = 224; picker.focusRingType = 1;
  picker.dateValue = (initial ? f.dateFromString(initial) : null) || $.NSDate.date;
  picker.sizeToFit;
  var pw = picker.frame.size.width, ph = picker.frame.size.height, pad = 10, footer = allowClear ? 30 : 0;
  var W = pw + 2 * pad, H = ph + 2 * pad + footer;
  var scr = $.NSScreen.screens.objectAtIndex(0).frame, screenH = scr.size.height, screenW = scr.size.width;
  var y = (yBelow + H > screenH - 40) ? Math.max(0, yAbove - H - 4) : yBelow;
  x = Math.max(0, Math.min(x, screenW - W));
  // панель не становится ключевым окном: фокус остаётся в поле ввода программы, а клики по календарю работают
  ObjC.registerSubclass({name: 'DPPanel', superclass: 'NSPanel', methods: {
    'canBecomeKeyWindow': {types: ['char', []], implementation: function () { return false; }},
    'canBecomeMainWindow': {types: ['char', []], implementation: function () { return false; }}
  }});
  var panel = $.DPPanel.alloc.initWithContentRectStyleMaskBackingDefer($.NSMakeRect(x, screenH - y - H, W, H),
      $.NSWindowStyleMaskBorderless | $.NSWindowStyleMaskNonactivatingPanel, 2, false);
  panel.becomesKeyOnlyIfNeeded = true; panel.floatingPanel = true;
  if (look) panel.appearance = $.NSAppearance.appearanceNamed(look === 'dark' ? 'NSAppearanceNameDarkAqua' : 'NSAppearanceNameAqua');
  panel.opaque = false; panel.backgroundColor = $.NSColor.clearColor; panel.level = 3; panel.hasShadow = true;
  var fx = $.NSVisualEffectView.alloc.initWithFrame($.NSMakeRect(0, 0, W, H));
  fx.material = 6; fx.blendingMode = 0; fx.state = 1; fx.wantsLayer = true; fx.layer.cornerRadius = 10; fx.layer.masksToBounds = true;
  panel.contentView = fx;
  picker.setFrameOrigin($.NSMakePoint(pad, pad + footer));
  fx.addSubview(picker);
  var done = false;
  function finish(r) {
    if (done) return; done = true;
    var out = $.NSString.alloc.initWithUTF8String(r + '\n');
    $.NSFileHandle.fileHandleWithStandardOutput.writeData(out.dataUsingEncoding($.NSUTF8StringEncoding));
    $.exit(0);
  }
  ObjC.registerSubclass({name: 'DPTarget', methods: {
    'picked:': {types: ['void', ['id']], implementation: function (s) { finish('OK:' + ObjC.unwrap(f.stringFromDate(picker.dateValue))); }},
    'cleared:': {types: ['void', ['id']], implementation: function (s) { finish('CLEAR'); }},
    'sync:': {types: ['void', ['id']], implementation: function (t) {         // календарь следует за датой, набранной в поле
      if (!syncPath) return;
      var s = $.NSString.stringWithContentsOfFileEncodingError(syncPath, $.NSUTF8StringEncoding, $());
      if (s && ObjC.unwrap(s)) { var d = f.dateFromString(ObjC.unwrap(s).trim()); if (d) picker.dateValue = d; }
    }},
    'auto:': {types: ['void', ['id']], implementation: function (t) {         // только для автоматической проверки
      finish(auto === 'clear' ? 'CLEAR' : 'OK:' + ObjC.unwrap(f.stringFromDate(picker.dateValue)));
    }}
  }});
  var tgt = $.DPTarget.alloc.init;
  picker.target = tgt; picker.action = 'picked:';
  var modes = $.NSRunLoopCommonModes;
  $.NSRunLoop.mainRunLoop.addTimerForMode($.NSTimer.timerWithTimeIntervalTargetSelectorUserInfoRepeats(0.15, tgt, 'sync:', $(), true), modes);
  if (allowClear) {
    var b = $.NSButton.alloc.initWithFrame($.NSMakeRect(pad, 6, W - 2 * pad, 22));
    b.title = 'Очистить'; b.bezelStyle = 1; b.controlSize = 1; b.font = $.NSFont.systemFontOfSize(11); b.target = tgt; b.action = 'cleared:';
    fx.addSubview(b);
  }
  if (auto) $.NSRunLoop.mainRunLoop.addTimerForMode($.NSTimer.timerWithTimeIntervalTargetSelectorUserInfoRepeats(1.2, tgt, 'auto:', $(), false), modes);
  panel.orderFrontRegardless;
  app.run;
}
"""

_WIN_TEMPLATE = r"""
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @"
using System.Windows.Forms;
public class NoActivateForm : Form {
  protected override bool ShowWithoutActivation { get { return true; } }
  protected override CreateParams CreateParams { get { CreateParams p = base.CreateParams; p.ExStyle |= 0x08000088; return p; } }
}
"@
[System.Windows.Forms.Application]::EnableVisualStyles()
$inv = [System.Globalization.CultureInfo]::InvariantCulture
$sync = '@@SYNC@@'
$form = New-Object NoActivateForm
$form.FormBorderStyle = 'None'
$form.ShowInTaskbar = $false
$form.TopMost = $true
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point(@@X@@, @@Y@@)
$form.Padding = New-Object System.Windows.Forms.Padding(1)
$form.BackColor = [System.Drawing.SystemColors]::ControlDark
$cal = New-Object System.Windows.Forms.MonthCalendar
$cal.MaxSelectionCount = 1
$cal.Location = New-Object System.Drawing.Point(1, 1)
@@SET_DATE@@
$form.Controls.Add($cal)
$h = $cal.Height + 2
$script:finished = $false
function Finish($text) { if (-not $script:finished) { $script:finished = $true; [Console]::Out.WriteLine($text); [Console]::Out.Flush(); $form.Close() } }
$cal.Add_DateSelected({ Finish ('OK:' + $cal.SelectionStart.ToString('yyyy-MM-dd', $inv)) })
@@CLEAR_BUTTON@@
$form.ClientSize = New-Object System.Drawing.Size(($cal.Width + 2), $h)
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 150
$timer.Add_Tick({
  if ($sync -and (Test-Path $sync)) {
    $t = (Get-Content -Raw -Path $sync).Trim()
    try { $d = [datetime]::ParseExact($t, 'yyyy-MM-dd', $inv); if ($cal.SelectionStart.Date -ne $d.Date) { $cal.SetDate($d) } } catch {}
  }
})
$timer.Start()
$form.Show()
[System.Windows.Forms.Application]::Run($form)
"""

_WIN_CLEAR = r"""$clear = New-Object System.Windows.Forms.Button
$clear.Text = 'Очистить'; $clear.FlatStyle = 'System'; $clear.Size = New-Object System.Drawing.Size(($cal.Width - 2), 24)
$clear.Location = New-Object System.Drawing.Point(2, ($cal.Height + 2))
$clear.Add_Click({ Finish 'CLEAR' })
$form.Controls.Add($clear)
$h = $cal.Height + 30"""


class NativeUnavailable(OSError):
    pass


def available() -> bool:
    """Есть ли на этом компьютере системный выбор даты (macOS с osascript или Windows с PowerShell)."""
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None
    if sys.platform.startswith("win"):
        return shutil.which("powershell") is not None
    return False


def windows_script(initial: str, allow_clear: bool, x: int, y: int, sync_path: str = "") -> str:
    safe = lambda s: str(s).replace("'", "''")
    set_date = f"$cal.SetDate([datetime]::ParseExact('{safe(initial)}', 'yyyy-MM-dd', $inv))" if initial else ""
    return (_WIN_TEMPLATE.replace("@@SYNC@@", safe(sync_path)).replace("@@X@@", str(int(x))).replace("@@Y@@", str(int(y)))
            .replace("@@SET_DATE@@", set_date).replace("@@CLEAR_BUTTON@@", _WIN_CLEAR if allow_clear else ""))


def build_command(initial: str, allow_clear: bool, x: int = 0, y: int = 0, platform: str | None = None, auto: str = "",
                  y_above: int | None = None, look: str = "", sync_path: str = "") -> tuple[list[str], dict]:
    """Команда запуска вспомогательного процесса для текущей (или заданной) платформы и параметры Popen.
    x, y — экранные координаты левого верхнего угла панели (под полем), y_above — верх поля (если снизу не помещается)."""
    platform = platform or sys.platform
    if platform == "darwin":
        above = y if y_above is None else y_above
        return (["osascript", "-l", "JavaScript", "-e", MAC_SCRIPT, initial, "1" if allow_clear else "0", str(int(x)), str(int(y)),
                 str(int(above)), auto, look, sync_path], {})
    if platform.startswith("win"):
        encoded = base64.b64encode(windows_script(initial, allow_clear, x, y, sync_path).encode("utf-16-le")).decode("ascii")
        return (["powershell", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                {"creationflags": 0x08000000})                                    # CREATE_NO_WINDOW: без чёрного окна консоли
    raise NativeUnavailable("системный выбор даты на этой системе недоступен")


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


class Pending:
    """Открытая системная панель календаря: можно передать ей дату, набранную в поле, и закрыть её."""

    def __init__(self, proc: subprocess.Popen | None, sync_path: str):
        self.proc, self.sync_path, self.cancelled = proc, sync_path, False

    def sync(self, d: date | None) -> None:
        """Календарь перейдёт на дату d (пустая дата — без изменений)."""
        if d is None:
            return
        try:
            with open(self.sync_path, "w", encoding="utf-8") as f:
                f.write(d.strftime("%Y-%m-%d"))
        except OSError:
            pass

    def cancel(self) -> None:
        self.cancelled = True
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()

    def _cleanup(self) -> None:
        try:
            os.unlink(self.sync_path)
        except OSError:
            pass


def ask(widget, current: date | None, allow_clear: bool, on_result, x: int = 0, y: int = 0, auto: str = "",
        y_above: int | None = None, look: str = "") -> Pending:
    """Показывает системный календарь, не блокируя интерфейс и не забирая фокус. on_result(kind, date): kind — pick / clear /
    cancel / error. Возвращает объект, которым календарь закрывают или переводят на другую дату."""
    fd, sync_path = tempfile.mkstemp(prefix="debtors-date-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(current.strftime("%Y-%m-%d") if current else "")
    pending = Pending(None, sync_path)
    try:
        cmd, kwargs = build_command(current.strftime("%Y-%m-%d") if current else "", allow_clear, x, y, auto=auto,
                                    y_above=y_above, look=look, sync_path=sync_path)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", **kwargs)
    except OSError:
        pending._cleanup()
        on_result("error", None)
        return pending
    pending.proc = proc

    def poll():
        if proc.poll() is None:
            try:
                widget.after(80, poll)
            except Exception:
                proc.kill()                                       # окно закрыли, пока календарь был открыт
                pending._cleanup()
            return
        out, _err = proc.communicate()
        pending._cleanup()
        if pending.cancelled:
            return
        if proc.returncode != 0:
            on_result("error", None)
        else:
            kind, d = parse_output(out)
            on_result(kind, d)
    poll()
    return pending
