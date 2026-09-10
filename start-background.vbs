' ---------------------------------------------------------------------------
'  Zaimu Entry (kaikei-soft)
'  Start the local server minimized, without opening a browser.
'  Used by the Windows auto-start shortcut created by autostart-on.bat.
'  Keep this file ASCII only: cscript/wscript read .vbs using the system
'  code page, so non-ASCII text here would be garbled.
' ---------------------------------------------------------------------------
Option Explicit

Dim sh, fso, base, q, cmdline

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FileExists(base & "\start.bat") Then
  MsgBox "start.bat not found in:" & vbCrLf & base, vbExclamation, "Zaimu Entry"
  WScript.Quit 1
End If

sh.CurrentDirectory = base
q = Chr(34)
cmdline = q & base & "\start.bat" & q & " --no-browser"

' 7 = minimized, not activated
sh.Run cmdline, 7, False
