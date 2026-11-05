; Olympus World installer (build with: makensis olympus_world.nsi)
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

!define APPNAME "Olympus World"
!define APPVER "1.2.0"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\OlympusWorld"
!define SRC ".."

Name "${APPNAME}"
OutFile "OlympusWorldSetup.exe"
InstallDir "$DOCUMENTS\Olympus World"
InstallDirRegKey HKCU "Software\OlympusWorld" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "Olympus World ${APPVER}"

VIProductVersion "1.2.0.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} Setup"
VIAddVersionKey "FileVersion" "${APPVER}"
VIAddVersionKey "LegalCopyright" "Personal project"

Var PYEXE

!define MUI_ICON "olympus.ico"
!define MUI_UNICON "olympus.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Welcome to Olympus World"
!define MUI_WELCOMEPAGE_TEXT "Zeus, Hephaestus and Athena will live on their own in a bare 3D world. They build, talk, read and keep diaries while you watch.$\r$\n$\r$\nThis is separate from your existing Olympus install. It won't change it.$\r$\n$\r$\nYou need Python 3.9 or newer (you already have it) and Ollama with qwen2.5:7b.$\r$\n$\r$\nClick Next to continue."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "Olympus World is installed"
!define MUI_FINISHPAGE_TEXT "There's an Olympus World icon on your desktop.$\r$\n$\r$\nFirst, let the setup check run. It tests everything and asks Zeus for one real thought."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Run the setup check now (recommended)"
!define MUI_FINISHPAGE_RUN_FUNCTION RunCheck
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Start Olympus World now"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION StartWorld
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

; ---------------------------------------------------------------- find python
Function TryPython
  ; $0 = command to try. On success sets $PYEXE.
  nsExec::ExecToStack '$0 -c "import sys; assert sys.version_info >= (3, 9); print(sys.executable)"'
  Pop $1
  Pop $2
  ${If} $1 == 0
    ; strip trailing newline characters
    trim:
      StrCpy $3 $2 1 -1
      ${If} $3 == "$\n"
      ${OrIf} $3 == "$\r"
      ${OrIf} $3 == " "
        StrCpy $2 $2 -1
        Goto trim
      ${EndIf}
    ${If} ${FileExists} "$2"
      StrCpy $PYEXE $2
    ${EndIf}
  ${EndIf}
FunctionEnd

Function FindPython
  StrCpy $PYEXE ""
  StrCpy $0 "py -3"
  Call TryPython
  ${If} $PYEXE == ""
    StrCpy $0 "python"
    Call TryPython
  ${EndIf}
  ${If} $PYEXE == ""
    ; per-user installs that were never added to PATH
    FindFirst $4 $5 "$LOCALAPPDATA\Programs\Python\Python3*"
    ${DoWhile} $5 != ""
      ${If} ${FileExists} "$LOCALAPPDATA\Programs\Python\$5\python.exe"
        StrCpy $0 '"$LOCALAPPDATA\Programs\Python\$5\python.exe"'
        Call TryPython
      ${EndIf}
      ${If} $PYEXE != ""
        ${Break}
      ${EndIf}
      FindNext $4 $5
    ${Loop}
    FindClose $4
  ${EndIf}
FunctionEnd

; ---------------------------------------------------------------- install
Section "Olympus World (required)" SecMain
  SectionIn RO
  Call FindPython
  ${If} $PYEXE == ""
    MessageBox MB_OK|MB_ICONSTOP "Couldn't find Python 3.9 or newer on this PC.$\r$\n$\r$\nInstall it from python.org (tick 'Add python.exe to PATH'), then run this installer again."
    Abort "Python not found."
  ${EndIf}
  DetailPrint "Using Python: $PYEXE"

  ; If the world is running, ask it to save and close before replacing its files.
  InitPluginsDir
  File "/oname=$PLUGINSDIR\stop_world.py" "${SRC}\tools\stop_world.py"
  stopcheck:
    nsExec::ExecToLog '"$PYEXE" "$PLUGINSDIR\stop_world.py" "$INSTDIR"'
    Pop $0
    ${If} $0 == 3
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Olympus World is running.$\r$\n$\r$\nClose the 'Olympus World' window in your taskbar (it saves when it closes), then click Retry." /SD IDCANCEL IDRETRY stopcheck
      Abort "Close Olympus World and run the installer again."
    ${EndIf}

  SetOutPath "$INSTDIR"
  ; remove old program files from a previous version (your world data is kept)
  RMDir /r "$INSTDIR\olympus_world"
  RMDir /r "$INSTDIR\web"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\tests"

  File "${SRC}\README.md"
  File "${SRC}\version.json"
  File "${SRC}\update.json"
  File "${SRC}\1_CHECK_SETUP.cmd"
  File "${SRC}\2_ADD_GEMINI_KEY.cmd"
  File "${SRC}\3_START_WORLD.cmd"
  File "${SRC}\TEST_MODE_NO_AI.cmd"
  File "olympus.ico"
  SetOutPath "$INSTDIR\olympus_world"
  File "${SRC}\olympus_world\*.py"
  SetOutPath "$INSTDIR\web"
  File "${SRC}\web\index.html"
  File "${SRC}\web\app.js"
  File "${SRC}\web\style.css"
  File "${SRC}\web\icon-256.png"
  SetOutPath "$INSTDIR\web\vendor"
  File "${SRC}\web\vendor\*.*"
  SetOutPath "$INSTDIR\tools"
  File "${SRC}\tools\*.py"
  SetOutPath "$INSTDIR\tests"
  File "${SRC}\tests\*.py"
  SetOutPath "$INSTDIR\config"
  SetOverwrite off            ; keep your own settings if you edited them
  File "${SRC}\config\settings.json"
  SetOverwrite on

  FileOpen $9 "$INSTDIR\python_path.txt" w
  FileWrite $9 "$PYEXE"
  FileClose $9

  ; Start menu
  SetOutPath "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\Olympus World"
  CreateShortcut "$SMPROGRAMS\Olympus World\Olympus World.lnk" "$PYEXE" "-m olympus_world.server" "$INSTDIR\olympus.ico" 0 SW_SHOWMINIMIZED "" "Start the world and open the viewer"
  CreateShortcut "$SMPROGRAMS\Olympus World\Olympus World - Check setup.lnk" "$PYEXE" '"$INSTDIR\tools\check.py"' "$INSTDIR\olympus.ico" 0 SW_SHOWNORMAL "" "Run the tests and check Ollama"
  CreateShortcut "$SMPROGRAMS\Olympus World\Olympus World - Add Gemini key.lnk" "$PYEXE" '"$INSTDIR\tools\set_gemini_key.py"' "$INSTDIR\olympus.ico" 0 SW_SHOWNORMAL "" "Save your Gemini key on this PC"
  CreateShortcut "$SMPROGRAMS\Olympus World\Olympus World - Test mode (no AI).lnk" "$PYEXE" "-m olympus_world.server --fake" "$INSTDIR\olympus.ico" 0 SW_SHOWMINIMIZED "" "A separate pretend world with random actions"
  CreateShortcut "$SMPROGRAMS\Olympus World\Olympus World - Read me.lnk" "$WINDIR\notepad.exe" '"$INSTDIR\README.md"'
  CreateShortcut "$SMPROGRAMS\Olympus World\Olympus World - Open folder.lnk" "$INSTDIR"
  CreateShortcut "$SMPROGRAMS\Olympus World\Uninstall Olympus World.lnk" "$INSTDIR\Uninstall Olympus World.exe"

  ; uninstaller + Apps list entry
  WriteUninstaller "$INSTDIR\Uninstall Olympus World.exe"
  WriteRegStr HKCU "Software\OlympusWorld" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${APPVER}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Olympus"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\olympus.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall Olympus World.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" $0
SectionEnd

Section "Desktop icon" SecDesktop
  SetOutPath "$INSTDIR"
  CreateShortcut "$DESKTOP\Olympus World.lnk" "$PYEXE" "-m olympus_world.server" "$INSTDIR\olympus.ico" 0 SW_SHOWMINIMIZED "" "Start the world and open the viewer"
SectionEnd

Section /o "Start Olympus World when I sign in" SecStartup
  SetOutPath "$INSTDIR"
  CreateShortcut "$SMSTARTUP\Olympus World.lnk" "$PYEXE" "-m olympus_world.server --no-browser" "$INSTDIR\olympus.ico" 0 SW_SHOWMINIMIZED "" "Keep the gods living whenever this PC is on"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "The world, the gods' minds, the 3D viewer and the setup tools."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "An Olympus World icon on your desktop that starts the world."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartup} "Starts the world quietly (minimized) every time you sign in. Uses your PC's graphics card for thinking while it runs."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function StartWorld
  SetOutPath "$INSTDIR"
  Exec '"$PYEXE" -m olympus_world.server'
FunctionEnd

Function RunCheck
  SetOutPath "$INSTDIR"
  Exec '"$PYEXE" "$INSTDIR\tools\check.py"'
FunctionEnd

; ---------------------------------------------------------------- uninstall
Section "Uninstall"
  Delete "$DESKTOP\Olympus World.lnk"
  Delete "$SMSTARTUP\Olympus World.lnk"
  RMDir /r "$SMPROGRAMS\Olympus World"

  RMDir /r "$INSTDIR\olympus_world"
  RMDir /r "$INSTDIR\web"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\tests"
  Delete "$INSTDIR\*.cmd"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\version.json"
  Delete "$INSTDIR\update.json"
  RMDir /r "$INSTDIR\backups"
  Delete "$INSTDIR\olympus.ico"
  Delete "$INSTDIR\python_path.txt"

  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "Also delete the gods' world (everything they built, their diaries and memories), your settings and your Gemini key?$\r$\n$\r$\nChoose No to keep them in $INSTDIR, so a reinstall picks up where they left off." /SD IDNO IDNO keep
    RMDir /r "$INSTDIR\data"
    RMDir /r "$INSTDIR\config"
  keep:
  Delete "$INSTDIR\Uninstall Olympus World.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\OlympusWorld"
SectionEnd
