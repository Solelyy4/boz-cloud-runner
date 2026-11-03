' BOZ bridge starter — dwibahasa, tahan path berubah, tiada tetingkap.
Option Explicit
Dim sh, fso, pfx, exe, script, cmd, wmi, procs, p, sudah, root
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\hermes"
script = root & "\elevated\laptop_bridge.py"
pfx = "C:/Users/zahin/AppData/Local/hermes/tools"

' cari python hermes secara dinamik (nama folder ada hash tarikh, jangan hardcode)
exe = ""
If fso.FolderExists(pfx) Then
  Dim f, sub_
  For Each f In fso.GetFolder(pfx).SubFolders
    If Left(f.Name, 7) = "python-" Then
      If fso.FileExists(f.Path & "\pythonw.exe") Then exe = f.Path & "\pythonw.exe"
      If exe = "" And fso.FileExists(f.Path & "\python.exe") Then exe = f.Path & "\python.exe"
    End If
    If Left(f.Name, 4) = "git-" Then
      ' git tak perlu di sini, hanya pastikan loop tak buang masa
    End If
  Next
End If
If exe = "" Then exe = "pythonw.exe"

sudah = False
Set wmi = GetObject("winmgmts:\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name LIKE 'python%'")
For Each p In procs
  If Not IsNull(p.CommandLine) Then
    If InStr(LCase(p.CommandLine), "laptop_bridge.py") > 0 Then sudah = True
  End If
Next

If sudah Then WScript.Quit 0

sh.CurrentDirectory = root & "\elevated"
cmd = """" & exe & """ """ & script & """"
sh.Run cmd, 0, False
