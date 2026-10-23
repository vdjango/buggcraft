Option Explicit

Dim shell, fso, root, python, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
python = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(python) Then python = root & "\venv\Scripts\pythonw.exe"
If Not fso.FileExists(python) Then python = "pythonw.exe"
command = Chr(34) & python & Chr(34) & " " & Chr(34) & root & "\src\buggcraft\main.py" & Chr(34)
shell.CurrentDirectory = root
shell.Run command, 0, False
