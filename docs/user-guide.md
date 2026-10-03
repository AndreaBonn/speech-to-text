**English** | [Italiano](./guida-utente.md)

# Transcriber user guide

Transcriber (called sbobina in the code) turns the recording of a lecture into written text. Everything happens on your computer: the audio is not sent over the internet.

Lectures are grouped by course. For each course you can also add the material you study from (book, slides, notes), search lectures and material together, create practice exams and summaries, and ask questions. These study features use a second free program, Ollama, which also runs on your computer.

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
9. [History, models and other pages](#history-models-and-other-pages)
10. [Installing Ollama (optional)](#installing-ollama-optional)
11. [Automatic correction](#automatic-correction)
12. [Courses](#courses)
13. [Searching lectures and material](#searching-lectures-and-material)
14. [Adding course material](#adding-course-material)
15. [Scanned PDFs: reading them with OCR](#scanned-pdfs-reading-them-with-ocr)
16. [Practice exams and summaries](#practice-exams-and-summaries)
17. [Asking questions about the course](#asking-questions-about-the-course)
18. [Study materials for a lecture](#study-materials-for-a-lecture)
19. [Closing the program](#closing-the-program)
20. [Where your files are](#where-your-files-are)
21. [If something goes wrong](#if-something-goes-wrong)

## What you need

- A computer with Windows 10 or 11, macOS or Linux.
- At least 8 GB of free disk space, plus about 6 GB if you want the study features with Ollama.
- An internet connection **for the first start only**: the program downloads Python, its libraries and the transcription model (between 2 and 4 GB in total). After that, transcription works offline.
- A recording of the lecture in one of these formats: m4a, mp3, wav, ogg, opus, flac, webm, aac. Phone recordings are fine.
- Optional: the course material as PDF, Word (`.docx`), PowerPoint (`.pptx`), plain text (`.txt`) or Markdown (`.md`) files.

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
2. In the **Materia** (Subject) field, type the course name, for example `Analisi matematica`. The lecture goes into that course on the **Corsi** page, and the automatic correction uses the name to recognize the course's terms. Always type the same name for lectures of the same course. You can leave it empty and assign the course later from the Reader.
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

**Changing the course of a lecture.** At the top of the Reader is the **Corso** (Course) field. Type the course name (while you type, the program suggests the courses that already exist) and click **Salva corso** (Save course). The lecture moves to that course on the **Corsi** page.

The **Materiali di studio** (Study materials) button opens the study page of this lecture: see [Study materials for a lecture](#study-materials-for-a-lecture).

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

## History, models and other pages

- **Storico** (History): every lecture you uploaded, with date and status. **Apri** opens it in the Reader, **Elimina** (Delete) removes the lecture and its files. Careful: **Elimina** does not ask for confirmation.
- **Modelli** (Models): the transcription models downloaded on your computer. You can download one here before using it, so the first transcription starts right away. You do not need to change the model: the program picks the right one for your computer (`large-v3` with an NVIDIA card, `large-v3-turbo` without). The **Ollama** section of the same page downloads the models for correction and the study features.
- **Confronto (WER)**: measures accuracy by comparing the transcript with a hand-written text. You can ignore it.
- **Tema** (Theme): the button at the bottom of the left menu switches the pages between **Auto** (follows your computer), **Chiaro** (light) and **Scuro** (dark).

## Installing Ollama (optional)

Ollama is a separate free program that runs a language model on your computer. Transcriber uses it for the automatic correction, the study materials, practice exams, summaries, questions about the course and reading scanned PDFs. Without Ollama, transcription, Reader, search and downloads work anyway.

Without an NVIDIA card these features are very slow: for long lectures it is better to skip them.

1. Go to https://ollama.com/download and download the version for your system.
2. Install Ollama:
   - **Windows and macOS**: open the downloaded file and follow the installer. Then open the Ollama app; on Windows it sits near the clock, on macOS in the top bar.
   - **Linux**: copy the command shown on the download page into Terminal and press **Enter**.
3. In Transcriber, open the **Modelli** page. In the **Ollama** section, in the **Scarica per nome** (Download by name) field, type `qwen3.5:9b` and click **Scarica** (Download). The download is about 6 GB. This model is used by all the study features.
4. Only if you have scanned PDFs: repeat step 3 with `qwen2.5vl:7b`, the model that reads page images. If you skip this, the program downloads it the first time you use OCR, and that first time takes longer.

If Ollama is not running, a yellow notice "Ollama non è disponibile" (Ollama is not available) may appear at the top of the pages: you can ignore it if you only transcribe.

## Automatic correction

The correction rereads the text and fixes misheard words, without rewriting sentences. It needs Ollama (see the previous section). With an RTX 4060, an 85-minute lecture is corrected in about 18 minutes.

1. On the **Nuova trascrizione** page, fill in **Materia**: the correction uses it to recognize the course's terms.
2. Tick **Correggi con Ollama dopo la trascrizione** (Correct with Ollama after transcription) before clicking **Trascrivi**.
3. When the job is done, the Reader shows the **Originale** and **Corretta** buttons, and the **Report correzioni** download lists every word that was changed.

## Courses

The **Corsi** (Courses) page lists your courses, with the number of lectures and the date of the last one. Lectures without a course are grouped under **Senza corso** (No course).

1. Click a course name. The course page opens.
2. At the top is the table of its lectures: click a lecture to open it in the Reader.
3. Below are three sections: **Materiali** (Material), **Esercitazioni e riassunti** (Practice exams and summaries) and **Domande sul corso** (Questions about the course). The next sections of this guide explain them.
4. To go back to the list, click **← Tutti i corsi** (All courses).

To move a lecture to another course, use the **Corso** field in the Reader (see [Reading and listening to the transcript](#reading-and-listening-to-the-transcript)).

## Searching lectures and material

At the top of the **Corsi** page is the search box **Cerca nelle lezioni e nei materiali** (Search lectures and material).

1. In **Parole o frase** (Words or phrase), type what you are looking for, for example `causa del contratto`. To find an exact phrase, put it in double quotes: `"causa del contratto"`. Similar forms are found too: `contratti` also finds `contratto`.
2. Optional: in **Corso**, choose a course. **Tutti i corsi** searches everywhere.
3. Click **Cerca** (Search).
4. Each result shows the lecture or document and the passage that matches.
   - For a lecture, click the time next to the passage (for example **12:30**): the Reader opens at that point.
   - For a document, click the link: the document opens on the matching page.

The first search can take a little longer, because the program indexes all the lectures.

## Adding course material

On a course page, the **Materiali** section holds the files you study from. Accepted formats: PDF, Word (`.docx`), PowerPoint (`.pptx`), plain text (`.txt`) and Markdown (`.md`), up to 200 MB per file.

1. Open the course on the **Corsi** page.
2. Drag the file into the box **Trascina un file qui o scegli** (Drag a file here or choose), or click the box and choose the file. One file at a time.
3. A progress bar shows the upload. Then the row shows a label:
   - **Caricamento** (Uploading) and then **Estrazione in corso** (Reading the text): wait, the page updates by itself.
   - **Pronto** (Ready): the text has been read. The document is now used by search, practice exams, summaries and questions.
   - **Pronto (senza testo)** (Ready, without text): the file has no readable text, usually a scanned PDF. See the next section.
   - **Errore** (Error): the file could not be read. The reason is written under the name.
4. On each row: **Apri** (Open) shows the text page by page, with **Precedente** and **Successiva** (Previous, Next) and **Scarica originale** (Download original); **Scarica** downloads the file; **Elimina** deletes it after asking for confirmation.

If the course page says "Per caricare materiali assegna prima un corso alla lezione" (assign a course to the lecture first), you are on **Senza corso**: material needs a real course. Assign the course from the Reader, then come back.

The same file cannot be uploaded twice into the same course.

## Scanned PDFs: reading them with OCR

A scanned PDF contains photos of pages, not text. The program can read them with OCR (optical character recognition) using the `qwen2.5vl:7b` model in Ollama. It is slow: on the project's computer each page takes 4 to 5 minutes. A single run stops after one hour, which at that speed is about 12 pages, and the text is saved only when every page has been read. For a longer scanned document, split the PDF into files of about 10 pages and upload them one by one.

1. In the **Materiali** section, find the row marked **Pronto (senza testo)**.
2. Click **Estrai il testo con OCR** (Extract the text with OCR).
3. The row shows **OCR in coda** (queued) and then **OCR: pagina 3 di 10** (page 3 of 10). You can leave the page and come back later.
4. To stop it, click **Annulla** (Cancel). Nothing is saved: the next run starts again from the first page.
5. When it finishes, the row shows **Pronto** and the document is used like the others.

Text read with OCR can contain mistakes, sometimes ones that change the meaning. Wherever it is cited, it is marked **testo da OCR** (text from OCR): check it against the original page before studying it.

## Practice exams and summaries

In the **Esercitazioni e riassunti** section of a course page you can create practice exams and summaries from the lectures and material of that course. It needs Ollama with `qwen3.5:9b`.

1. In **Formato** (Format), choose:
   - **Crocette**: multiple-choice questions
   - **Domande aperte**: open questions
   - **Orale**: questions for an oral exam
   - **Riassunto**: a summary
2. For exams, in **Numero di domande** (Number of questions), type a number from 1 to 10.
3. Optional: in **Argomento** (Topic), type a topic, for example `leggi di Newton`. Left empty, the program picks passages from the whole course.
4. Optional: open **Fonti** (Sources) and choose which documents and lectures to use. To choose more than one, hold **Ctrl** (on a Mac, **Cmd**) and click. No selection means the whole course.
5. Click **Genera** (Generate).
6. The new row in the list shows **In coda** (Queued), **In corso** (Running) and then **Completata** (Completed). With an RTX 4060 it takes between half a minute and a minute and a half. While it runs, **Annulla** stops it.
7. Click **Mostra** (Show) to read the result, **Nascondi** (Hide) to close it.

**Reading the result.** Every question, answer and summary sentence shows its source: the document name with the page (for example `manuale.pdf p.31`) or the lecture with the time, followed by the quoted sentence. Click the source to open the page of the document or the Reader at that point. For multiple-choice questions the correct option is marked **Corretta**, and open and oral questions have a **Soluzione** (Solution).

Questions whose quote cannot be found in the material are dropped. The result says how many were kept, for example **8 su 10 richieste** (8 of 10 requested), and why the others were dropped. If a document or a lecture was changed after the exam was created, its sources are marked **fonte modificata dopo la generazione** (source changed after generation).

**Downloading.** A completed exam has four download buttons: `compito.md` and `compito.docx` (the questions only, to do the exam), `soluzioni.md` and `soluzioni.docx` (questions with answers and sources). A summary has `riassunto.md` and `riassunto.docx`. The `.docx` files open in Word.

**Elimina** deletes a result after asking for confirmation.

Messages you may see:

| Message | What it means |
| --- | --- |
| "Nel materiale del corso non trovo questo argomento." | The topic does not appear in the course: try another word, or leave **Argomento** empty |
| "Nessun materiale disponibile per generare: carica documenti o lezioni in questo corso." | The course has no lectures or documents with text yet |
| "Il modello ha risposto in un formato non valido: riprova." | The model's reply could not be read: click **Genera** again |

## Asking questions about the course

In the **Domande sul corso** section you can ask questions and get an answer taken only from the lectures and material of that course. It needs Ollama with `qwen3.5:9b`.

1. Click **Nuova conversazione** (New conversation).
2. Type the question in **Domanda**, for example `Che cos'è l'avviamento?`.
3. Click **Invia** (Send). While you wait, the page shows "Sto cercando nel materiale…" (Searching the material). With an RTX 4060 the answer arrives in about 10 seconds; the first question after starting can take longer.
4. Every sentence of the answer has its source, as in the practice exams: click it to open the document page or the Reader at that point.
5. To continue on the same topic, write the next question in the same conversation.

If the answer is **"Non trovo la risposta nel materiale di questo corso."** (I cannot find the answer in this course's material), the course does not cover the question: the program does not answer from general knowledge.

Conversations stay in the list on the left: click one to reopen it. **Elimina** deletes it after asking for confirmation.

If you see "La scheda video è occupata da una trascrizione: riprova tra poco." (the graphics card is busy with a transcription), wait for the transcription to finish and ask again.

## Study materials for a lecture

For a single lecture, the program can prepare a summary, the key concepts and some likely exam questions. It needs Ollama with `qwen3.5:9b`.

1. Open the lecture in the Reader and click **Materiali di studio** (Study materials).
2. Click **Genera** (Generate). The program says it takes about twenty minutes for a lecture of an hour and a half. The page shows the progress; you can leave and come back.
3. The page shows three parts: **Riassunto** (Summary), **Concetti chiave** (Key concepts) and **Possibili domande d'esame** (Possible exam questions), split by part of the lecture.
4. Under each item is the sentence of the lecture it comes from, with paragraph and time (for example **§3 23:10**): click it to open the Reader at that point and listen.
5. To create them again, for example after correcting the transcript, click **Rigenera** (Generate again). **Torna al lettore** (Back to the reader) takes you back.

If the page says the material was generated on an older version of the transcript, you corrected the text after generating: click **Rigenera** to update it.

## Closing the program

- **Windows**: close the black window.
- **macOS and Linux**: in the Terminal window press **Ctrl** and **C** together, then close the window.

If you close it while a transcription is running, that lecture shows as **Interrotta** (Interrupted) at the next start: upload it again. The same happens to an exam, a summary or an OCR that was running: start it again from the course page.

## Where your files are

Everything stays in the `data` folder, inside the program folder: audio and transcripts of the lectures, and in `data/courses` the course material, practice exams, summaries and conversations. To free space, delete lectures from the **Storico** page and material from the course pages. If you move or delete the program folder, you also move or delete all of this.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| The browser does not open by itself | Open the browser and type `http://127.0.0.1:8765` in the address bar |
| "Porta 8765 già occupata" (port already in use) | The program is already open in another window: use that one, or close it and start again |
| The page does not load | Check that the black window (or Terminal) is still open; if you closed it, start the program again |
| Notice "Trascrizione su CPU: sarà più lenta" (transcribing on the CPU, slower) | Not an error: the computer has no usable NVIDIA card, transcription works but takes longer |
| "Ollama non è disponibile. Installa Ollama..." or "Scarica l'app Ollama..." | Install Ollama (see [Installing Ollama](#installing-ollama-optional)), or untick the automatic correction |
| "Ollama non è disponibile. Avvia l'app Ollama." (start the Ollama app) | Open the Ollama app and reload the page |
| "Ollama non è disponibile. Avvia ollama serve." (Linux) | Open a new Terminal, type `ollama serve`, press **Enter** and leave that window open |
| "Ollama non risponde: avvialo e riprova." (Ollama is not responding) | Open the Ollama app (on Linux, `ollama serve`), then click the button again |
| "La ricerca non è disponibile su questo computer" (search is not available) | The Python on this computer lacks a component needed by search; courses and Reader work anyway. Report it at the link below |
| "Il documento è in elaborazione: riprova tra poco." (the document is being processed) | Wait for the label to become **Pronto**, then try again |
| "OCR interrotto: ci stava mettendo troppo." (OCR stopped, it was taking too long) | The document has too many pages for one run: split the PDF into files of about 10 pages and upload them separately |
| "La generazione è in corso: annullala prima di eliminarla." | Click **Annulla** on that row, then **Elimina** |
| macOS: "Permission denied" or "Operation not permitted" | Make sure you typed `bash avvia.sh`, not `./avvia.sh` |
| An error appears in the window and the program stops | Take a photo of the screen and send it to whoever gave you the program, or open a report at https://github.com/AndreaBonn/speech-to-text/issues |
| The transcript has many wrong words | Record closer to the speaker; check the yellow words; try the automatic correction |
