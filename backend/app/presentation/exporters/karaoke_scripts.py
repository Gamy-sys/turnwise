"""Runtime karaoke scripts + their timing feed.

Strategy B (PowerPoint VBA) and Strategy C (LibreOffice Basic/UNO) both drive the
highlight by **character position**, reading a simple line feed so no fragile
JSON parsing is needed inside a macro. The feed and scripts are emitted as
sidecars next to the presentation by the service; keeping them together is why
exports are bundled as a .zip.
"""
from __future__ import annotations

from ..project import PresentationProject


def timing_feed(project: PresentationProject) -> str:
    """One line per word: ``slideIndex|start|end|charStart|charLength|word``.

    ``slideIndex`` is 1-based to match PowerPoint's Slides collection; the body
    text box is the second shape on each content slide (title is first).
    """
    title_offset = 1 if project.options.include_title_slide else 0
    lines = ["# slideIndex|start|end|charStart|charLength|word"]
    for s in project.slides:
        sidx = s.index + 1 + title_offset
        for w in s.words:
            lines.append(f"{sidx}|{w.start:.3f}|{w.end:.3f}|"
                         f"{w.char_start}|{w.char_length}|{w.word}")
    return "\n".join(lines) + "\n"


# Highlight colour applied to the active word (BGR long for VBA, hex for Basic).
def _bgr(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def vba_module(project: PresentationProject) -> str:
    hi = _bgr(project.theme.highlight_bg)
    base = _bgr(project.theme.fg)
    audio = project.audio.filename if project.audio else "audio.mp3"
    body_shape = 2 if project.options.include_title_slide else 2  # title textbox = shape 1
    return f"""Attribute VB_Name = "Karaoke"
' CA Studio - Strategy B: VBA runtime word highlighting.
' Keep presentation.pptm, timing.txt and {audio} together in one folder.
' Run Karaoke_Play from the Developer tab (macros must be enabled).

Private Declare PtrSafe Function timeGetTime Lib "winmm.dll" () As Long

Private Const HI As Long = {hi}
Private Const BASECOL As Long = {base}
Private Const BODY_SHAPE As Long = {body_shape}

Private mSlide() As Long, mStart() As Double, mCS() As Long, mLen() As Long
Private mN As Long

Public Sub Karaoke_Play()
    If Not LoadTiming() Then Exit Sub
    PlayAudio
    Dim t0 As Long: t0 = timeGetTime()
    Dim i As Long, lastSlide As Long, lastCS As Long, lastLen As Long
    lastSlide = -1
    Do
        Dim now As Double: now = (timeGetTime() - t0) / 1000#
        For i = 0 To mN - 1
            If now >= mStart(i) Then
                If i = mN - 1 Or now < mStart(i + 1) Then
                    If Not (mSlide(i) = lastSlide And mCS(i) = lastCS) Then
                        If lastSlide > 0 Then SetColor lastSlide, lastCS, lastLen, BASECOL
                        GotoSlide mSlide(i)
                        SetColor mSlide(i), mCS(i), mLen(i), HI
                        lastSlide = mSlide(i): lastCS = mCS(i): lastLen = mLen(i)
                    End If
                    Exit For
                End If
            End If
        Next i
        DoEvents
        If now > mStart(mN - 1) + 3 Then Exit Do
    Loop
End Sub

Private Function LoadTiming() As Boolean
    Dim path As String: path = ActivePresentation.path & "\\timing.txt"
    If Dir(path) = "" Then MsgBox "timing.txt not found next to the file.": Exit Function
    ReDim mSlide(0 To 20000): ReDim mStart(0 To 20000)
    ReDim mCS(0 To 20000): ReDim mLen(0 To 20000)
    Dim f As Integer: f = FreeFile
    Open path For Input As #f
    Dim line As String, parts() As String
    mN = 0
    Do While Not EOF(f)
        Line Input #f, line
        If Left(line, 1) <> "#" And InStr(line, "|") > 0 Then
            parts = Split(line, "|")
            mSlide(mN) = CLng(parts(0)): mStart(mN) = CDbl(parts(1))
            mCS(mN) = CLng(parts(3)): mLen(mN) = CLng(parts(4))
            mN = mN + 1
        End If
    Loop
    Close #f
    LoadTiming = (mN > 0)
End Function

Private Sub SetColor(ByVal sld As Long, ByVal cs As Long, ByVal ln As Long, ByVal col As Long)
    On Error Resume Next
    ActivePresentation.Slides(sld).Shapes(BODY_SHAPE) _
        .TextFrame.TextRange.Characters(cs + 1, ln).Font.Color.RGB = col
End Sub

Private Sub GotoSlide(ByVal sld As Long)
    On Error Resume Next
    If SlideShowWindows.Count > 0 Then
        SlideShowWindows(1).View.GotoSlide sld
    Else
        ActivePresentation.Windows(1).View.GotoSlide sld
    End If
End Sub

Private Sub PlayAudio()
    On Error Resume Next
    Dim wmp As Object
    Set wmp = CreateObject("WMPlayer.OCX")
    wmp.URL = ActivePresentation.path & "\\{audio}"
    wmp.controls.play
End Sub
"""


def basic_module(project: PresentationProject) -> str:
    hi = int(project.theme.highlight_bg.lstrip("#"), 16)
    base = int(project.theme.fg.lstrip("#"), 16)
    audio = project.audio.filename if project.audio else "audio.mp3"
    return f"""' CA Studio - Strategy C: LibreOffice Basic / UNO runtime word highlighting.
' Tools > Macros > Edit Macros, paste into a module, run KaraokePlay.
' Keep the .odp, timing.txt and {audio} in the same folder.
' Uses only standard LibreOffice Basic (no VBA-only functions).

Const HI As Long = {hi}
Const BASECOL As Long = {base}

Sub KaraokePlay
    Dim oDoc As Object, oSlides As Object
    oDoc = ThisComponent
    oSlides = oDoc.DrawPages

    Dim sDir As String
    sDir = ParentUrl(oDoc.getURL())

    Dim iFile As Integer : iFile = FreeFile
    Dim n As Integer : n = 0
    Dim slideA(20000) As Integer, startA(20000) As Double, csA(20000) As Long, lenA(20000) As Long
    Dim sLine As String, parts() As String
    Open ConvertFromURL(sDir & "timing.txt") For Input As #iFile
    Do While Not EOF(iFile)
        Line Input #iFile, sLine
        If Left(sLine, 1) <> "#" And InStr(sLine, "|") > 0 Then
            parts = Split(sLine, "|")
            slideA(n) = CInt(parts(0)) - 1   ' 0-based DrawPages
            startA(n) = CDbl(parts(1))
            csA(n) = CLng(parts(3)) : lenA(n) = CLng(parts(4))
            n = n + 1
        End If
    Loop
    Close #iFile
    If n = 0 Then
        MsgBox "No timing rows found. Is timing.txt next to this file?"
        Exit Sub
    End If

    ' play audio (ignore if the media backend is unavailable)
    On Error Resume Next
    Dim oPlayer As Object, oAudio As Object
    oPlayer = createUnoService("com.sun.star.media.Manager")
    oAudio = oPlayer.createPlayer(sDir & "{audio}")
    oAudio.start()
    On Error Goto 0

    Dim t0 As Double : t0 = Timer
    Dim i As Integer, lastSlide As Integer, lastCS As Long, lastLen As Long
    i = 0 : lastSlide = -1
    Do While i < n
        Dim nowT As Double : nowT = Timer - t0
        If nowT >= startA(i) Then
            If lastSlide >= 0 Then SetChar(oSlides, lastSlide, lastCS, lastLen, BASECOL)
            SetChar(oSlides, slideA(i), csA(i), lenA(i), HI)
            lastSlide = slideA(i) : lastCS = csA(i) : lastLen = lenA(i)
            i = i + 1
        End If
        Wait 15
    Loop
End Sub

' Folder URL of the document: everything up to and including the last "/".
Function ParentUrl(sFull As String) As String
    Dim k As Integer, p As Integer
    p = 0
    For k = 1 To Len(sFull)
        If Mid(sFull, k, 1) = "/" Then p = k
    Next k
    ParentUrl = Left(sFull, p)
End Function

Sub SetChar(oSlides As Object, iSlide As Integer, cs As Long, ln As Long, col As Long)
    On Error Resume Next
    Dim oPage As Object, oBox As Object, oText As Object, oCur As Object
    oPage = oSlides.getByIndex(iSlide)
    oBox = oPage.getByIndex(1)          ' body text box (title is index 0)
    oText = oBox.getText()
    oCur = oText.createTextCursor()
    oCur.gotoStart(False)
    oCur.goRight(cs, False)
    oCur.goRight(ln, True)
    oCur.CharColor = col
End Sub
"""
