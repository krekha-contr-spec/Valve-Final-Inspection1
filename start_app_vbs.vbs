Set WshShell = CreateObject("WScript.Shell")
scriptPath = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
WshShell.Run Chr(34) & scriptPath & "start_app.bat" & Chr(34), 0, False
WScript.Sleep 3000
Set WshShell = Nothing
