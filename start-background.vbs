' ---------------------------------------------------------------------------
'  Zaimu Entry (kaikei-soft)
'  Start the local server minimized, without opening a browser.
'  Used by the Windows auto-start shortcut created by autostart-on.bat.
'
'  Keep this file ASCII only: wscript reads .vbs using the system code page,
'  so non-ASCII text here would be garbled.
'  Use "+" (not "&") for string concatenation so that autostart-on.bat can
'  regenerate this file with plain ECHO lines when it is missing.
' ---------------------------------------------------------------------------
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
Set env = sh.Environment("PROCESS")
env("KAIKEI_NO_BROWSER") = "1"
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
sh.Run Chr(34) + base + "\start.bat" + Chr(34) + " --no-browser", 7, False
