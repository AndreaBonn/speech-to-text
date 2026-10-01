**English** | [Italiano](./guida-utente.md)

# Transcriber user guide

Transcriber (called sbobina in the code) turns the recording of a lecture into written text. Everything happens on your computer: the audio is not sent over the internet.

This guide covers Windows, macOS and Linux. You do not need to know how to program: just follow the steps in order.

The program's pages and messages are in Italian, because it was built for Italian lectures. This guide quotes them as they appear on screen, with the English meaning next to them the first time.

## Contents

1. [What you need](#what-you-need)
2. [Downloading the program](#downloading-the-program)
3. [First start](#first-start)
4. [Starting it again](#starting-it-again)
5. [Transcribing a lecture](#transcribing-a-lecture)
6. [Reading and listening to the transcript](#reading-and-listening-to-the-transcript)
7. [Correcting by hand](#correcting-by-hand)
8. [Downloading the text](#downloading-the-text)
9. [History and models](#history-and-models)
10. [Automatic correction with Ollama (optional)](#automatic-correction-with-ollama-optional)
11. [Closing the program](#closing-the-program)
12. [Where your files are](#where-your-files-are)
13. [If something goes wrong](#if-something-goes-wrong)

## What you need

- A computer with Windows 10 or 11, macOS or Linux.
- At least 8 GB of free disk space.
- An internet connection **for the first start only**: the program downloads Python, its libraries and the transcription model (between 2 and 4 GB in total). After that, transcription works offline.
- A recording of the lecture in one of these formats: m4a, mp3, wav, ogg, opus, flac, webm, aac. Phone recordings are fine.

An NVIDIA graphics card makes everything much faster, but it is not required. On a Mac, transcription always runs on the processor.

**How long it takes.** With an NVIDIA RTX 4060 graphics card, an 85-minute lecture is transcribed in about 6 and a half minutes. Without an NVIDIA card, on a laptop with a 13th-generation Intel Core i7 processor, a 90-minute lecture takes about half an hour. An older computer may take longer; the page shows the remaining time, calculated on your lecture.

> The program is developed and tested on Linux. Windows and macOS are supported in the code but have not yet been tried on many computers: if something does not work, see [If something goes wrong](#if-something-goes-wrong).

## Downloading the program

If someone already gave you the program folder, skip to step 5.

1. Open your browser and go to https://github.com/AndreaBonn/speech-to-text
2. Click the green **Code** button.
3. In the menu that opens, click **Download ZIP**. A file called `speech-to-text-main.zip` starts downloading.
4. Open your computer's **Downloads** folder and find the file you just downloaded.
5. Extract the ZIP file:
   - **Windows**: right-click the file, then **Extract All...**, then **Extract**.
   - **macOS**: double-click the file.
   - **Linux**: right-click the file, then **Extract Here**.
6. You now have a folder called `speech-to-text-main`. Move it wherever you like, for example to **Documents**. Avoid the Desktop of a work computer synced with OneDrive or iCloud: the program has many files and syncing slows it down.

## First start

Pick the section for your system. The first time takes a few minutes, because the program prepares everything it needs.

### Windows

1. Open the `speech-to-text-main` folder.
2. Double-click the `avvia.bat` file ("avvia" means "start"). If file names do not show `.bat` at the end, there are two files called `avvia`: pick the one Windows describes as **Windows Batch File** (hover the mouse over it to see the description).
3. If a blue box says "Windows protected your PC", click **More info** and then **Run anyway**.
4. A black window opens. The first time it asks: `Lo installo ora da https://astral.sh/uv/install.ps1 [S,N]?` ("Shall I install it now?"). Press the **S** key (for "sì", yes). This installs Python and the libraries.
5. Wait. Lines of text scroll in the black window: that is normal. When everything is ready, the browser opens by itself on the page `http://127.0.0.1:8765`.

**Keep the black window open** while you use the program. You can minimize it, but do not close it.

### macOS

1. Open the **Terminal** app: press **Cmd** and **Space** together, type `Terminal` and press **Return**. A window with some text opens.
2. In Terminal, type `cd` followed by a space. Do not press Return yet.
3. Open Finder, find the `speech-to-text-main` folder and drag it into the Terminal window. The folder path appears after `cd `.
4. Press **Return**.
5. Type this command and press **Return**:

   ```
   bash avvia.sh
   ```

6. The first time it asks: `Lo installo ora da https://astral.sh/uv/install.sh? [S/n]` ("Shall I install it now?"). Press **Return** (it means yes). This installs Python and the libraries.
7. Wait. When everything is ready, the browser opens by itself on the page `http://127.0.0.1:8765`.

**Keep the Terminal window open** while you use the program.

### Linux

1. Open the `speech-to-text-main` folder in your file manager.
2. Right-click an empty area of the folder, then **Open in Terminal**. If that option is missing, open Terminal from the applications menu, type `cd ` (with the space), drag the folder into the window and press **Enter**.
3. Type this command and press **Enter**:

   ```
   bash avvia.sh
   ```

4. The first time it asks: `Lo installo ora da https://astral.sh/uv/install.sh? [S/n]` ("Shall I install it now?"). Press **Enter** (it means yes).
5. If you see `Manca curl` ("curl is missing"), type `sudo apt install curl`, press **Enter**, type your computer password (nothing appears while you type, that is normal) and repeat step 3. This command works on Ubuntu, Debian and Linux Mint.
6. Wait. When everything is ready, the browser opens by itself on the page `http://127.0.0.1:8765`.

**Keep the Terminal window open** while you use the program.

### What the program tells you at startup

In the first lines of the window the program says, in Italian, what it will use. For example:

```
Sistema linux: trascrivo con GPU NVIDIA (float16), modello large-v3.
```

("Linux system: transcribing with the NVIDIA GPU, model large-v3"), or, without an NVIDIA card, a line saying it transcribes with the **processore** (processor). Both are fine: the processor is just slower.

## Starting it again

From the second time on, the program starts in a few seconds and asks nothing.

- **Windows**: double-click `avvia.bat`.
- **macOS and Linux**: open Terminal in the folder (as in steps 1-4 of the first start) and type `bash avvia.sh`.

## Transcribing a lecture

The page that opens is called **Nuova trascrizione** (New transcription). The menu on the left leads to the other pages.

1. Drag the audio file into the **File audio** box, or click the box and choose the file from your disk.
2. Optional: in the **Materia** (Subject) field, type the course name, for example `Analisi matematica`. Only the automatic correction uses it (see below).
3. Click **Trascrivi** (Transcribe).
4. On the right, in the **Coda** (Queue) section, the lecture appears with a progress bar. You can upload more lectures: they wait their turn.
5. When the row says **Completata** (Completed), click **Apri** (Open).

While a transcription runs you can close the browser and reopen it on `http://127.0.0.1:8765`: the work goes on as long as the black window (or Terminal) stays open. To stop a transcription, click **Annulla** (Cancel) on its row.

You can leave **Impostazioni avanzate** (Advanced settings) alone: the defaults are fine for lectures.

## Reading and listening to the transcript

The **Lettore** (Reader) page shows the text split into paragraphs, each with its start time.

- Words **highlighted in yellow** are the ones the model is unsure about: check them.
- Next to the text is the list of **punti da riascoltare** (passages to listen to again).
- **Click a word** and the audio plays from that point.
- At the bottom of the page is the audio player: play/pause button, **−10s** and **+10s** to jump back or forward 10 seconds, the position bar and the speed (1×, 1.25×, 1.5×).

If you used the automatic correction, two buttons appear at the top, **Originale** and **Corretta** (Corrected), to switch between the two versions.

## Correcting by hand

1. In the Reader, click **Correggi a mano** (Correct by hand). The **Correzione manuale** box opens at the bottom.
2. Click the wrong word, or hold the mouse button and drag over a whole phrase. To extend the selection, hold **Shift** and click another word.
3. Type the right text in the box.
4. Click **Salva** (Save), or press **Enter**. To give up, click **Annulla** (Cancel), or press **Esc**.

The **Riascolta** (Listen again) button plays the audio from the selected words. If you leave the box empty and save, the selected words are deleted.

## Downloading the text

At the top of the Reader there are download buttons:

| Button | What you get | When to use it |
| --- | --- | --- |
| **Scarica .docx** | Word document, clean text without timestamps | To study or print |
| **Scarica .txt** | Plain text, without timestamps | To paste it anywhere |
| **Scarica .md** | Text with timestamps and uncertain words marked `[?like this?]` | To review the transcript |
| **Scarica .json** | Full technical data | Only for developers |
| **Scarica corretta (.md)** | Version corrected by Ollama | Only after automatic correction |
| **Report correzioni** | List of the words Ollama changed | Only after automatic correction |

The `.docx` and `.txt` buttons download the version you are looking at (Originale or Corretta).

## History and models

- **Storico** (History): every lecture you uploaded, with date and status. **Apri** opens it in the Reader, **Elimina** (Delete) removes the lecture and its files. Careful: **Elimina** does not ask for confirmation.
- **Modelli** (Models): the transcription models downloaded on your computer. You can download one here before using it, so the first transcription starts right away. You do not need to change the model: the program picks the right one for your computer (`large-v3` with an NVIDIA card, `large-v3-turbo` without).
- **Confronto (WER)**: measures accuracy by comparing the transcript with a hand-written text. You can ignore it.

## Automatic correction with Ollama (optional)

The correction rereads the text and fixes misheard words, without rewriting sentences. It uses a separate free program, Ollama, which also runs on your computer.

Without an NVIDIA card the correction is very slow: for a long lecture it is better to skip it. With an RTX 4060, an 85-minute lecture is corrected in about 18 minutes.

1. Go to https://ollama.com/download and download the version for your system.
2. Install Ollama:
   - **Windows and macOS**: open the downloaded file and follow the installer. Then open the Ollama app; on Windows it sits near the clock, on macOS in the top bar.
   - **Linux**: copy the command shown on the download page into Terminal and press **Enter**.
3. In Transcriber, open the **Modelli** page. In the **Ollama** section, in the **Scarica per nome** (Download by name) field, type `qwen3.5:9b` and click **Scarica** (Download). The download is about 6 GB.
4. On the **Nuova trascrizione** page, tick **Correggi con Ollama dopo la trascrizione** (Correct with Ollama after transcription) before clicking **Trascrivi**.

If you do not use Ollama, a yellow notice "Ollama non è disponibile" (Ollama is not available) may appear at the top of the pages: you can ignore it, transcription works anyway.

## Closing the program

- **Windows**: close the black window.
- **macOS and Linux**: in the Terminal window press **Ctrl** and **C** together, then close the window.

If you close it while a transcription is running, that lecture shows as **Interrotta** (Interrupted) at the next start: upload it again.

## Where your files are

Audio and transcripts stay in the `data` folder, inside the program folder. To free space, delete lectures from the **Storico** page. If you move or delete the program folder, you also move or delete your transcripts.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| The browser does not open by itself | Open the browser and type `http://127.0.0.1:8765` in the address bar |
| "Porta 8765 già occupata" (port already in use) | The program is already open in another window: use that one, or close it and start again |
| The page does not load | Check that the black window (or Terminal) is still open; if you closed it, start the program again |
| Notice "Trascrizione su CPU: sarà più lenta" (transcribing on the CPU, slower) | Not an error: the computer has no usable NVIDIA card, transcription works but takes longer |
| "Ollama non è disponibile. Installa Ollama..." or "Scarica l'app Ollama..." | Install Ollama (see above), or untick the automatic correction |
| "Ollama non è disponibile. Avvia l'app Ollama." (start the Ollama app) | Open the Ollama app and reload the page |
| "Ollama non è disponibile. Avvia ollama serve." (Linux) | Open a new Terminal, type `ollama serve`, press **Enter** and leave that window open |
| macOS: "Permission denied" or "Operation not permitted" | Make sure you typed `bash avvia.sh`, not `./avvia.sh` |
| An error appears in the window and the program stops | Take a photo of the screen and send it to whoever gave you the program, or open a report at https://github.com/AndreaBonn/speech-to-text/issues |
| The transcript has many wrong words | Record closer to the speaker; check the yellow words; try the automatic correction |
