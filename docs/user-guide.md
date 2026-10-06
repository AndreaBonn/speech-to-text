**English** | [Italiano](./guida-utente.md)

# Transcriber user guide

Transcriber (called sbobina in the code) turns the recording of a lecture into written text. Everything happens on your computer: the audio is not sent over the internet.

Lectures are grouped by course. For each course you can add the material you study from (book, slides, notes), search lectures and material together, create practice exams and summaries, take the practice exams and have them graded, ask questions and review with flashcards. The study features use a second free program, Ollama, which also runs on your computer.

This guide covers Windows, macOS and Linux. You do not need to know how to program: just follow the steps in order.

The program's pages and messages are in Italian, because it was built for Italian lectures. This guide quotes them as they appear on screen, with the English meaning next to them the first time.

## Contents

1. [What you need](#what-you-need)
2. [Downloading the program](#downloading-the-program)
3. [First start](#first-start)
4. [Starting it again](#starting-it-again)
5. [Updating the program](#updating-the-program)
6. [Transcribing a lecture](#transcribing-a-lecture)
7. [Reading and listening to the transcript](#reading-and-listening-to-the-transcript)
8. [Correcting by hand](#correcting-by-hand)
9. [Downloading the text](#downloading-the-text)
10. [History, models and other pages](#history-models-and-other-pages)
11. [Installing Ollama (optional)](#installing-ollama-optional)
12. [Automatic correction](#automatic-correction)
13. [Courses](#courses)
14. [Searching lectures and material](#searching-lectures-and-material)
15. [Adding course material](#adding-course-material)
16. [Scanned PDFs: reading them with OCR](#scanned-pdfs-reading-them-with-ocr)
17. [Math formulas](#math-formulas)
18. [Practice exams and summaries](#practice-exams-and-summaries)
19. [Taking a practice exam](#taking-a-practice-exam)
20. [Exam cues](#exam-cues)
21. [Asking questions about the course](#asking-questions-about-the-course)
22. [Study materials for a lecture](#study-materials-for-a-lecture)
23. [Reviewing with flashcards](#reviewing-with-flashcards)
24. [Exporting and importing a course](#exporting-and-importing-a-course)
25. [Closing the program](#closing-the-program)
26. [Where your files go](#where-your-files-go)
27. [If something goes wrong](#if-something-goes-wrong)

## What you need

- A computer with Windows 10 or 11, macOS or Linux.
- At least 8 GB of free disk space, plus about 6 GB if you want the study features with Ollama.
- An internet connection **only for the first start**: the program downloads Python, the libraries and the transcription model (between 2 and 4 GB in total). After that, transcription works offline too.
- A recording of the lecture in one of these formats: m4a, mp3, wav, ogg, opus, flac, webm, aac. Phone recordings are fine.
- Optional: the course material as PDF, Word (`.docx`), PowerPoint (`.pptx`), plain text (`.txt`) or Markdown (`.md`) files.

An NVIDIA graphics card makes everything much faster, but it is not required. On a Mac, transcription always uses the processor.

**How long it takes.** With an NVIDIA RTX 4060 graphics card, an 85-minute lecture is transcribed in about 6 and a half minutes. Without an NVIDIA card, on a laptop with a 13th-generation Intel Core i7 processor, a 90-minute lecture takes about half an hour. An older computer may take longer; the page shows the time left, calculated on your lecture.

> The program is developed and tested on Linux. Everything is in place for Windows and macOS, but it has not been tried on many computers yet: if something does not work, see [If something goes wrong](#if-something-goes-wrong).

## Downloading the program

If someone already gave you the program folder, skip to [First start](#first-start).

There are two ways to download it. With **Git** (recommended) you type two commands once, and afterwards updating the program is a single command. With the **ZIP file** you install nothing, but for every update you have to download everything again by hand.

### No GitHub account?

You do not need one. The program is public: to download it with Git or as a ZIP you do not have to sign up for or log in to GitHub. An account is only needed to open an issue report (see [If something goes wrong](#if-something-goes-wrong)).

What you do need is **Git**, a free program that downloads the code and keeps it up to date. Install it following the section for your system.

#### Installing Git on Windows

1. Open the browser and go to https://git-scm.com/downloads/win
2. Click **Click here to download**. A file called `Git-` followed by the version number starts downloading, for example `Git-2.51.0-64-bit.exe`.
3. Open the downloaded file from the **Downloads** folder. If Windows asks "Do you want to allow this app to make changes to your device?", click **Yes**.
4. The installer asks many questions: keep the choices it already proposes and click **Next** on every screen, then **Install**, then **Finish**.

#### Installing Git on macOS

1. Open the **Terminal** app: press **Cmd** and **Space** together, type `Terminal` and press **Enter**.
2. Type this command and press **Enter**:

   ```
   git --version
   ```

3. If a line like `git version 2.39.5` appears, Git is already there: go to [Cloning the program](#cloning-the-program).
4. If instead a window opens offering to install the **command line developer tools**, click **Install**, then **Agree**. The download takes a few minutes.
5. When the installation is done, repeat step 2: `git version` followed by a number must appear.

#### Installing Git on Linux

1. Open Terminal from the applications menu.
2. Type this command and press **Enter** (it works on Ubuntu, Debian and Linux Mint):

   ```
   sudo apt install git
   ```

3. Type your computer password and press **Enter**. Nothing shows while you type it: that is normal.
4. If it asks `Do you want to continue? [Y/n]`, press **Enter**.

### Cloning the program

"Cloning" means downloading the program folder with Git, so that it can be updated.

1. Open a terminal in the **Documents** folder:
   - **Windows**: open File Explorer and go to **Documents**. Click the address bar at the top (where the path is written), delete the text, type `cmd` and press **Enter**. A black window opens, already in **Documents**.
   - **macOS**: open Terminal (Cmd + Space, `Terminal`, Enter), type `cd Documents` and press **Enter**.
   - **Linux**: open Terminal, type `cd ~/Documents` and press **Enter**. If you see "No such file or directory", type `cd ~/Documenti` and press **Enter**.
2. Type this command and press **Enter**:

   ```
   git clone https://github.com/AndreaBonn/speech-to-text.git
   ```

3. A few lines appear, ending with `done.`. Now **Documents** has a folder called `speech-to-text`: that is the program folder.
4. If you see `git: command not found` or `'git' is not recognized as an internal or external command`, Git is not installed: go back to the section for your system. On Windows, if you have just installed it, close the black window and open it again as in step 1.

### Alternatively: the ZIP file

1. Open the browser and go to https://github.com/AndreaBonn/speech-to-text
2. Click the green **Code** button.
3. In the menu that opens, click **Download ZIP**. A file called `speech-to-text-main.zip` starts downloading.
4. Open the computer's **Downloads** folder and find the file you just downloaded.
5. Extract the ZIP file:
   - **Windows**: right-click the file, then **Extract All...**, then **Extract**.
   - **macOS**: double-click the file.
   - **Linux**: right-click the file, then **Extract Here**.
6. You now have a folder called `speech-to-text-main`: that is the program folder. Move it wherever you like, for example into **Documents**.

Whichever way you choose, do not put the folder on the Desktop of a work computer synced with OneDrive or iCloud: the program has many files and syncing slows it down.

## First start

In the steps below, "the program folder" is `speech-to-text` if you cloned it with Git, `speech-to-text-main` if you used the ZIP file. The first time takes a few minutes, because the program sets up everything it needs.

### Windows

1. Open the program folder.
2. Double-click the `avvia.bat` file. If you do not see `.bat` at the end of file names, there are two `avvia` files: pick the one Windows describes as **Windows Batch File** (you see it when you hover the mouse over it).
3. If a blue box "Windows protected your PC" appears, click **More info** and then **Run anyway**.
4. A black window opens. The first time it asks: `Lo installo ora da https://astral.sh/uv/install.ps1 [S,N]?` (Shall I install it now?). Press the **S** key (for *sì*, yes). This is the program that installs Python and the libraries.
5. Wait. Lines of text scroll in the black window: that is normal. When everything is ready, the browser opens by itself on the page `http://127.0.0.1:8765`.

**The black window must stay open** while you use the program. You can minimize it, but do not close it.

### macOS

1. Open the **Terminal** app: press **Cmd** and **Space** together, type `Terminal` and press **Enter**. A window with some text opens.
2. In Terminal, type `cd` followed by a space. Do not press Enter yet.
3. Open Finder, find the program folder and drag it into the Terminal window. The folder path appears after `cd `.
4. Press **Enter**.
5. Type this command and press **Enter**:

   ```
   bash avvia.sh
   ```

6. The first time it asks: `Lo installo ora da https://astral.sh/uv/install.sh? [S/n]` (Shall I install it now?). Press **Enter** (it means yes). This is the program that installs Python and the libraries.
7. Wait. When everything is ready, the browser opens by itself on the page `http://127.0.0.1:8765`.

**The Terminal window must stay open** while you use the program.

### Linux

1. Open the program folder in the file manager.
2. Right-click an empty space in the folder, then **Open in Terminal**. If that option is missing, open Terminal from the applications menu, type `cd ` (with the space), drag the folder into the window and press **Enter**.
3. Type this command and press **Enter**:

   ```
   bash avvia.sh
   ```

4. The first time it asks: `Lo installo ora da https://astral.sh/uv/install.sh? [S/n]` (Shall I install it now?). Press **Enter** (it means yes).
5. If you see `Manca curl` (curl is missing), type `sudo apt install curl`, press **Enter**, type your computer password (nothing shows while you type it, that is normal) and then repeat step 3. The command works on Ubuntu, Debian and Linux Mint.
6. Wait. When everything is ready, the browser opens by itself on the page `http://127.0.0.1:8765`.

**The Terminal window must stay open** while you use the program.

### What the program tells you at startup

In the first lines of the window the program writes, in Italian, what it will use. For example:

```
Sistema linux: trascrivo con GPU NVIDIA (float16), modello large-v3.
```

("Linux system: transcribing with NVIDIA GPU"), or, without an NVIDIA card, a line saying it transcribes with the **processore** (processor). Both are fine: the processor is just slower.

## Starting it again

From the second time on, the program starts in a few seconds and asks nothing.

- **Windows**: double-click `avvia.bat`.
- **macOS and Linux**: open Terminal in the program folder (as in steps 1-4 of the first start) and type `bash avvia.sh`.

## Updating the program

Your lectures, courses and everything you created live in the `data` folder, which updating does not touch.

**If you cloned with Git:**

1. Close the program (see [Closing the program](#closing-the-program)).
2. Open a terminal in the program folder, as in steps 1-4 of the first start. On Windows: open the folder in File Explorer, click the address bar, type `cmd` and press **Enter**.
3. Type this command and press **Enter**:

   ```
   git pull
   ```

4. If you see `Already up to date.`, you already had the latest version. Otherwise the list of changed files appears.
5. Start the program as usual. If the update brought new libraries, the first start after it takes a little longer.

**If you used the ZIP file:**

1. Close the program.
2. Download the ZIP again and extract it, as in [Alternatively: the ZIP file](#alternatively-the-zip-file).
3. Copy the `data` folder from the old program folder into the new one.
4. Start the program from the new folder. Once you have checked that your lectures and courses are there, you can delete the old folder.

## Transcribing a lecture

The page that opens is called **Nuova trascrizione** (New transcription). The menu on the left leads to the other pages: **Nuova trascrizione**, **Corsi** (Courses), **Ripasso** (Review), **Lettore** (Reader), **Storico** (History), **Modelli** (Models) and **Confronto (WER)** (Comparison).

1. Drag the audio file into the **File audio** box, or click the box and choose the file from your disk.
2. In the **Materia** (Subject) field, type the course name, for example `Analisi matematica`. The lecture goes into that course on the **Corsi** page, and the automatic correction uses the name to recognize the course's terms. Always type the same name for lectures of the same course. You can leave it empty and assign the course later from the Reader.
3. Click **Trascrivi** (Transcribe).
4. On the right, in the **Coda** (Queue) section, the lecture appears with a progress bar. You can upload more lectures: they wait their turn.
5. When the row says **Completata** (Completed), click **Apri** (Open).

While a transcription runs you can close the browser and reopen it on `http://127.0.0.1:8765`: the work goes on as long as the black window (or Terminal) stays open. To stop a transcription, click **Annulla** (Cancel) on its row.

You can leave **Impostazioni avanzate** (Advanced settings) alone: the defaults are fine for lectures.

## Reading and listening to the transcript

The **Lettore** (Reader) page shows the text split into paragraphs, each with its start time. The **Lettore** menu item opens the latest completed lecture; it stays greyed out until you have transcribed at least one.

- Words **highlighted in yellow** are the ones the model is unsure about: check them.
- Next to the text is the list of **punti da riascoltare** (passages to listen to again).
- **Click a word** and the audio plays from that point. As the audio plays, the word you hear is highlighted.
- At the bottom of the page is the audio player: play/pause button, **−10s** and **+10s** to jump back or forward 10 seconds, the position bar and the speed (1×, 1.25×, 1.5×).

If you used the automatic correction, two buttons appear at the top, **Originale** and **Corretta** (Corrected), to switch between the two versions.

**Changing the course of a lecture.** At the top of the Reader is the **Corso** (Course) field. Type the course name (while you type, the program suggests the courses that already exist) and click **Salva corso** (Save course). The lecture moves to that course on the **Corsi** page.

**Creating a flashcard.** Select a phrase of the text with the mouse: the **Crea carta** (Create card) button appears. Click it, check **Fronte** (Front, the question) and **Retro** (Back, the answer) and confirm. The card goes into the **Ripasso** of the lecture's course: see [Reviewing with flashcards](#reviewing-with-flashcards). The lecture needs a course.

The **Materiali di studio** (Study materials) button opens the study page of this lecture: see [Study materials for a lecture](#study-materials-for-a-lecture).

Lectures that came from an imported course have no audio: clicking a word or a time moves the text to that point, but you hear nothing.

## Correcting by hand

1. In the Reader, click **Correggi a mano** (Correct by hand). The **Correzione manuale** box opens at the bottom.
2. Click the wrong word, or hold the mouse button and drag over a whole phrase. To extend the selection, hold **Shift** and click another word.
3. Type the right text in the box.
4. Click **Salva** (Save), or press **Enter**. To give up, click **Annulla** (Cancel), or press **Esc**.

The **Riascolta** (Listen again) button plays the audio from the selected words. If you leave the box empty and save, the selected words are deleted.

If the same lecture is open in another browser tab and you already edited it there, the save is refused instead of overwriting: reload the page and make the correction again.

## Downloading the text

At the top of the Reader are the download buttons:

| Button | What you get | When to use it |
| --- | --- | --- |
| **Scarica .docx** | Word document, clean text without times | To study or print |
| **Scarica .txt** | Plain text, without times | To paste it anywhere |
| **Scarica .md** | Text with times and uncertain words marked `[?like this?]` | To double-check the transcript |
| **Scarica .json** | Full technical data | Only for developers |
| **Scarica corretta (.md)** | Version corrected by Ollama | Only after automatic correction |
| **Report correzioni** | List of the words Ollama changed | Only after automatic correction |

The `.docx` and `.txt` files download the version you are looking at (Originale or Corretta).

## History, models and other pages

- **Storico** (History): the list of all uploaded lectures, with date and status. **Apri** opens the Reader, **Elimina** (Delete) removes the lecture and its files. Careful: **Elimina** does not ask for confirmation.
- **Modelli** (Models): the transcription models downloaded on the computer. Here you can download one before using it, so the first transcription starts right away. You do not need to change the model: the program picks the right one for your computer (`large-v3` with an NVIDIA card, `large-v3-turbo` without) and marks it **In uso ora** (In use now). The **Ollama** section of the same page downloads the models for correction and the study features.
- **Confronto (WER)**: measures accuracy by comparing the transcript with a text written by hand. You can ignore it.
- **Tema** (Theme): the button at the bottom of the left menu switches the look of the pages between **Auto** (follows the computer), **Chiaro** (Light) and **Scuro** (Dark).

## Installing Ollama (optional)

Ollama is a separate, free program that runs a language model on your computer. Transcriber uses it for automatic correction, study materials, practice exams, summaries, grading your answers, questions about the course and reading scanned PDFs. Without Ollama, transcription, the Reader, search, downloads, exam cues and Ripasso still work.

Without an NVIDIA card these features are very slow: for long lectures it is better not to use them.

1. Go to https://ollama.com/download and download the version for your system.
2. Install Ollama:
   - **Windows and macOS**: open the downloaded file and follow the installer. Then open the Ollama app; on Windows it sits next to the clock, on macOS in the top bar.
   - **Linux**: copy the command shown on the download page into Terminal and press **Enter**.
3. In Transcriber, open the **Modelli** page. In the **Ollama** section, in the **Scarica per nome** (Download by name) field, type `qwen3.5:9b` and click **Scarica** (Download). The download is about 6 GB. This model is used by all the study features.
4. Only if you have scanned PDFs: repeat step 3 with `qwen2.5vl:7b`, the model that reads page images. If you skip this step, the program downloads it the first time you use OCR, and that first time takes longer.

If Ollama is not running, a yellow notice "Ollama non è disponibile" (Ollama is not available) may appear at the top of the pages: if you only need to transcribe, you can ignore it.

## Automatic correction

The correction rereads the text and fixes misheard words, without rewriting sentences. It needs Ollama (see the previous section). With an RTX 4060, an 85-minute lecture is corrected in about 18 minutes.

1. On the **Nuova trascrizione** page, fill in **Materia**: the correction uses it to recognize the course's terms.
2. Tick **Correggi con Ollama dopo la trascrizione** (Correct with Ollama after transcription) before clicking **Trascrivi**.
3. When the work is done, the Reader shows the **Originale** and **Corretta** buttons, and the **Report correzioni** download lists every changed word.

Correction is requested at upload: the interface has no button to correct a lecture that is already transcribed.

## Courses

The **Corsi** (Courses) page lists your courses, with the number of lectures and the date of the latest one. Lectures without a course are under **Senza corso** (No course).

1. Click a course name. The course page opens.
2. At the top is the table of its lectures: click a lecture to open it in the Reader, or **Materiali di studio** for its study page.
3. Below are the sections **Frasi da esame** (Exam cues), **Materiali** (Material), **Esercitazioni e riassunti** (Practice exams and summaries), **Tentativi** (Attempts), **Errori da ripassare** (Mistakes to review) and **Domande sul corso** (Questions about the course). The next sections of this guide explain them.
4. The **Esporta il corso** (Export the course) button creates a package to take to another computer: see [Exporting and importing a course](#exporting-and-importing-a-course).
5. To go back to the list, click **← Tutti i corsi** (All courses).

To move a lecture to another course, use the **Corso** field in the Reader (see [Reading and listening to the transcript](#reading-and-listening-to-the-transcript)).

## Searching lectures and material

At the top of the **Corsi** page is the search box **Cerca nelle lezioni e nei materiali** (Search lectures and material).

1. In **Parole o frase** (Words or phrase), type what you are looking for, for example `causa del contratto`. To find an exact phrase, put it in quotes: `"causa del contratto"`. It also finds similar forms: `contratti` also finds `contratto`.
2. Optional: in **Corso**, pick a course. **Tutti i corsi** (All courses) searches everywhere.
3. Click **Cerca** (Search).
4. Each result shows the lecture or document and the matching passage.
   - For a lecture, click the time next to the passage (for example **12:30**): the Reader opens at that point.
   - For a document, click its name: the document opens on the page that was found, with the searched words highlighted.

The first search may take a little longer, because the program indexes all lectures.

## Adding course material

On a course page, the **Materiali** section collects the files you study from. Accepted formats: PDF, Word (`.docx`), PowerPoint (`.pptx`), plain text (`.txt`) and Markdown (`.md`), up to 200 MB per file.

1. Open the course from the **Corsi** page.
2. Drag the file into the **Trascina un file qui o scegli** (Drag a file here or choose) box, or click the box and choose the file. One file at a time.
3. A bar shows the upload. Then a label appears on the row:
   - **Caricamento** (Uploading) and then **Estrazione in corso** (Extracting): wait, the page updates by itself.
   - **Pronto** (Ready): the text has been read. From now on the document is part of search, practice exams, summaries and questions.
   - **Pronto (senza testo)** (Ready, no text): the file has no readable text, usually a scanned PDF. See the next section.
   - **Errore** (Error): the file could not be read. The reason is written under its name.
4. On each row: **Apri** shows the text page by page, with **Precedente** (Previous), **Successiva** (Next) and **Scarica originale** (Download original); **Scarica** downloads the file; **Elimina** deletes it after asking for confirmation.

If the course page says "Per caricare materiali assegna prima un corso alla lezione" (To upload material, first assign a course to the lecture), you are in **Senza corso**: material needs a real course. Assign the course from the Reader, then come back.

The same file cannot be uploaded twice to the same course.

## Scanned PDFs: reading them with OCR

A scanned PDF contains photos of the pages, not text. The program can read them with OCR (optical character recognition) using Ollama's `qwen2.5vl:7b` model. It is slow: on the project's computer each page takes 4 to 5 minutes. A single run stops after one hour, that is about 12 pages at that speed, and the text is saved only once every page has been read. For a longer scanned document, split the PDF into files of about 10 pages and upload them one at a time.

1. In the **Materiali** section, find the row marked **Pronto (senza testo)**.
2. Click **Estrai il testo con OCR** (Extract the text with OCR).
3. The row shows **OCR in coda** (OCR queued) and then **OCR: pagina 3 di 10** (page 3 of 10). You can leave the page and come back later.
4. To stop it, click **Annulla**. Nothing is saved: the next run starts again from the first page.
5. At the end the row says **Pronto** and the document works like the others.

Text read with OCR may contain errors, sometimes enough to change the meaning. Wherever it is quoted it is marked **testo da OCR** (OCR text): compare it with the original page before you study from it. OCR also transcribes the formulas on slides, which then appear formatted (see the next section).

## Math formulas

Formulas written by the model (in practice exams, summaries, chat answers, study materials and Ripasso cards) and formulas read with OCR appear formatted as in a book, with fractions, superscripts and symbols. You do not need to do anything: it happens by itself.

If a formula is malformed and cannot be formatted, its raw text appears instead, for example `\frac{a}{b`. The rest of the page still reads normally.

## Practice exams and summaries

In the **Esercitazioni e riassunti** section of a course page you can create practice exams and summaries from that course's lectures and material. It needs Ollama with `qwen3.5:9b`.

1. In **Formato** (Format), choose:
   - **Crocette**: multiple-choice questions
   - **Domande aperte**: open questions
   - **Orale**: questions for an oral exam
   - **Riassunto**: summary
2. For practice exams, in **Numero di domande** (Number of questions) type a number from 1 to 10.
3. Optional: in **Argomento** (Topic) type a topic, for example `leggi di Newton`. If you leave it empty, the program takes passages from the whole course.
4. Optional: open **Fonti** (Sources) and choose which documents and lectures to use. To choose more than one, hold **Ctrl** (on a Mac, **Cmd**) and click. With nothing selected it uses the whole course.
5. Click **Genera** (Generate).
6. The new row in the list shows **In coda** (Queued), **In corso** (Running) and then **Completata**. With an RTX 4060 it takes between half a minute and a minute and a half. While it runs, **Annulla** stops it.
7. Click **Mostra** (Show) to read the result, **Nascondi** (Hide) to close it. To take a practice exam, click **Svolgi** (Take it): see [Taking a practice exam](#taking-a-practice-exam).

**Reading the result.** Every question, answer and summary sentence shows its source: the document name with the page (for example `manuale.pdf p.31`) or the lecture with the time, followed by the quoted sentence. Click the source to open the document page or the Reader at that point. In multiple-choice questions the right option is marked **Corretta**. Open and oral questions have a **Soluzione** (Solution) split into points: the points a good answer has to cover.

Questions whose quote cannot be found in the material are dropped. The result says how many are left, for example **8 su 10 richieste** (8 of 10 requested), and why the others were dropped. If a document or lecture changed after the generation, its sources are marked **fonte modificata dopo la generazione** (source changed after generation).

Each practice exam and summary also has a page of its own, with the result and the downloads: you reach it, for example, from the source of a Ripasso card created from that practice exam.

**Downloading.** A completed practice exam has four buttons: `compito.md` and `compito.docx` (questions only, to take the test), `soluzioni.md` and `soluzioni.docx` (questions with answers and sources). A summary has `riassunto.md` and `riassunto.docx`. The `.docx` files open in Word.

**Elimina** deletes a result after asking for confirmation.

Messages you may see:

| Message | What it means |
| --- | --- |
| "Nel materiale del corso non trovo questo argomento." | The topic is not in the course: try another word, or leave **Argomento** empty |
| "Nessun materiale disponibile per generare: carica documenti o lezioni in questo corso." | The course has no lectures or documents with text yet |
| "Il modello ha risposto in un formato non valido: riprova." | The model's reply could not be read: click **Genera** again |

## Taking a practice exam

1. In the **Esercitazioni e riassunti** section, on a completed practice exam, click **Svolgi**. A page with all the questions opens.
2. For **multiple choice**: pick an option and click **Verifica** (Check). You see whether it is right and which answer is correct.
3. For **open** and **oral** questions: type your answer in the box and click **Verifica**.
4. Your answer is graded in one of two ways, depending on the computer:
   - **With an NVIDIA card** the model grades it: it tells you **Corretta**, **Parziale** (Partial) or **Errata** (Wrong), which **Punti che hai coperto** (Points you covered, with the sentence of your answer that covers each), which **Punti che mancano** (Missing points), and the solution with its sources.
   - **Without an NVIDIA card** automatic grading would be too slow: read the solution and choose your own grade with the **Mi do il voto: Corretta / Parziale / Errata** (I grade myself) buttons.

   Even when the model grades, you can change the grade with **Mi do il voto**: yours counts.
5. You can close the page halfway through. In the **Tentativi** (Attempts) section of the course page each attempt shows how many answers you handed in and the score, for example **6 di 10 consegnate · punteggio 4,5 su 10** (6 of 10 handed in, score 4.5 out of 10). **Riprendi** (Resume) reopens an unfinished attempt, **Apri** a finished one.

If an answer stays **Da valutare** (To be graded), for example because Ollama was not responding or the graphics card was busy with a transcription, click **Valuta** (Grade) to try again, or grade it yourself.

**Mistakes to review.** The **Errori da ripassare** section of the course page collects the wrong or partial answers from all attempts, with their grade and the solution's sources. **Crea carta** turns a mistake into a Ripasso flashcard; afterwards the button reads **Nel Ripasso** (In Ripasso).

## Exam cues

The program searches the transcripts for sentences where the lecturer signals what will be asked, such as "all'esame" (in the exam), "vi chiederò" (I will ask you), "ricordatevelo" (remember this) or "domanda d'esame" (exam question). It finds them by itself, without Ollama.

1. Open the course page. The **Frasi da esame** section lists these sentences, grouped by lecture.
2. At first you see only strong signals. Tick **Mostra anche i segnali deboli** (Also show weak signals) to also see sentences with words like "importante" or "fondamentale", which are often not about the exam.
3. Click the time of a sentence to open the Reader at that point and listen to the context.
4. **Crea carta** opens flashcard creation with the sentence already written on the back: type the question on the front and confirm.

## Asking questions about the course

In the **Domande sul corso** section you can ask questions and get an answer taken only from that course's lectures and material. It needs Ollama with `qwen3.5:9b`.

1. Click **Nuova conversazione** (New conversation).
2. Type the question in **Domanda** (Question), up to 1000 characters, for example `Che cos'è l'avviamento?`.
3. Click **Invia** (Send). While you wait, the page shows "Sto cercando nel materiale…" (Searching the material). With an RTX 4060 the answer arrives in about 10 seconds; the first question after startup may take longer.
4. Each sentence of the answer has its source, as in practice exams: click it to open the document page or the Reader at that point.
5. To continue on the same topic, type the next question in the same conversation.

If the answer is **"Non trovo la risposta nel materiale di questo corso."** (I cannot find the answer in this course's material), the course does not cover the question: the program does not answer from general knowledge.

Conversations stay in the list on the left: click one to reopen it. **Elimina** deletes it after asking for confirmation.

If you see "La scheda video è occupata da una trascrizione: riprova tra poco." (The graphics card is busy with a transcription: try again shortly), wait for the transcription to finish and ask again.

## Study materials for a lecture

For a single lecture the program can prepare a summary, the key concepts and some possible exam questions. It needs Ollama with `qwen3.5:9b`.

1. Open the lecture in the Reader and click **Materiali di studio**.
2. Click **Genera**. According to the program, a lecture of an hour and a half takes about twenty minutes. The page shows the progress; you can leave and come back.
3. The page shows three parts: **Riassunto** (Summary), **Concetti chiave** (Key concepts) and **Possibili domande d'esame** (Possible exam questions), split by part of the lecture.
4. Under each item is the lecture sentence it comes from, with paragraph and time (for example **§3 23:10**): click it to open the Reader at that point and listen.
5. **Aggiungi i concetti al mazzo** (Add the concepts to the deck) turns the key concepts into Ripasso flashcards; then **Vai al ripasso** (Go to review) appears. The lecture needs a course. If you click it again, concepts already in the deck are not duplicated.
6. To create them again, for example after correcting the transcript, click **Rigenera** (Regenerate). **Torna al lettore** (Back to the reader) takes you back to the lecture.

If the page says the material was generated on an earlier version of the transcript, you corrected the text after the generation: click **Rigenera** to update it.

## Reviewing with flashcards

**Ripasso** (Review) shows you each card on the right day: the ones you know well come back after many days, the ones you get wrong come back soon. The schedule uses FSRS, a spaced repetition algorithm. It does not need Ollama.

Cards are created in four ways:

- from the Reader, by selecting a phrase (see [Reading and listening to the transcript](#reading-and-listening-to-the-transcript));
- from **Materiali di studio**, with **Aggiungi i concetti al mazzo**;
- from **Frasi da esame**, with **Crea carta**;
- from **Errori da ripassare**, with **Crea carta**.

To review:

1. Click **Ripasso** in the left menu. The **Oggi** (Today) screen shows, for each course, how many cards are due today.
2. Click **Ripassa** (Review) on the course. If it says **Nessuna carta oggi** (No cards today), you are done for that course.
3. Read the front, think of the answer and click **Mostra risposta** (Show answer), or press the **space bar**.
4. Compare with the answer and choose how easy it was: **Di nuovo** (Again, key **1**), **Difficile** (Hard, **2**), **Bene** (Good, **3**) or **Facile** (Easy, **4**).
5. The next card follows. At the end you see "Per oggi hai finito." (You are done for today). **Torna a Oggi** (Back to Today) returns to the summary at any time.

The back of every card shows its source, with **Apri la fonte** (Open the source) to go back to the lecture or document. A label says whether the source is still as it was when you created the card: **Fonte verificata** (verified), **Fonte spostata** (moved: the text is there but somewhere else, for example after a correction), **Fonte modificata** (changed), **Fonte rimossa** (removed) or **Fonte non leggibile ora** (not readable right now).

At most 20 new cards per course enter each day, so the review does not get too long when you add many at once. In the interface, cards can be created and reviewed, but not edited or deleted.

## Exporting and importing a course

You can take a course to another computer, or pass it to a classmate who uses Transcriber, with a `.sbobina.zip` package.

**Exporting:**

1. Open the course page and click **Esporta il corso**.
2. In the window that opens, choose the **Materiali da includere** (Material to include): one checkbox per document, with the space it takes.
3. Click **Esporta** (Export). The browser downloads the package.

The package contains the lecture transcripts (without audio), the chosen material, the practice exams and the Ripasso cards. Cancelled or unfinished lectures are left out, and the final message says so.

Before sharing a package, remember that books and slides are often protected by copyright, and that transcripts may contain the voices and names of other students.

**Importing:**

1. Open the **Corsi** page.
2. In the **Importa un corso** (Import a course) section, drag the `.sbobina.zip` file into the box, or click the box and choose it.
3. A bar shows the upload, then "Controllo e copia del pacchetto: può richiedere qualche minuto." (Checking and copying the package: it may take a few minutes).
4. At the end, click **Apri il corso** (Open the course).

The imported course arrives as a new course, next to the ones you already have. Its lectures have no audio: you can read them, search them and use them for study, but you cannot listen to them or transcribe them again.

## Closing the program

- **Windows**: close the black window.
- **macOS and Linux**: in the Terminal window press **Ctrl** and **C** together, then close the window.

If you close it while a transcription is running, at the next start that lecture shows as **Interrotta** (Interrupted): upload it again. The same goes for a practice exam, a summary or an OCR run in progress: start it again from the course page. An interrupted import is deleted at the next start: repeat it.

## Where your files go

Everything stays in the `data` folder, inside the program folder: lecture audio and transcripts and, in `data/courses`, course material, practice exams, summaries, attempts, Ripasso cards and conversations. To free up space, delete lectures from the **Storico** page and material from the course pages. If you move or delete the program folder, you move or delete all of this too: to keep a copy, copy the `data` folder or export your courses.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| `git: command not found` or `'git' is not recognized as an internal or external command` | Git is not installed, or the window was opened before installing it: see [No GitHub account?](#no-github-account), then open a new window |
| `git pull` says `Your local changes would be overwritten` | You edited one of the program's files by hand: type `git stash` and then `git pull` again |
| The browser does not open by itself | Open the browser and type `http://127.0.0.1:8765` in the address bar |
| "Porta 8765 già occupata" (Port 8765 already in use) | The program is already open in another window: use that one, or close it and restart |
| The page does not load | Check that the black window (or Terminal) is still open; if you closed it, restart the program |
| Notice "Trascrizione su CPU: sarà più lenta" (Transcription on CPU: it will be slower) | Not an error: the computer has no usable NVIDIA card, transcription works but takes longer |
| "Ollama non è disponibile. Installa Ollama..." or "Scarica l'app Ollama..." | Install Ollama (see [Installing Ollama](#installing-ollama-optional)), or untick the automatic correction |
| "Ollama non è disponibile. Avvia l'app Ollama." (Start the Ollama app) | Open the Ollama app and reload the page |
| "Ollama non è disponibile. Avvia ollama serve." (Linux) | Open a new Terminal, type `ollama serve`, press **Enter** and leave that window open |
| "Ollama non risponde: avvialo e riprova." (Ollama is not responding) | Open the Ollama app (on Linux `ollama serve`), then click the button again |
| "GPU occupata da una trascrizione: valuta più tardi." (GPU busy with a transcription) | Wait for the transcription to finish, then click **Valuta** on the answer |
| "Nessun corso associato a questa lezione: imposta un corso per creare carte." (No course for this lecture) | Assign a course to the lecture with the **Corso** field in the Reader, then create the card again |
| "La ricerca non è disponibile su questo computer" (Search is not available on this computer) | This computer's Python lacks a component search needs; courses and the Reader still work. Report it at the link below |
| "Il documento è in elaborazione: riprova tra poco." (The document is being processed) | Wait until the label turns **Pronto**, then try again |
| "OCR interrotto: ci stava mettendo troppo." (OCR stopped: it was taking too long) | The document has too many pages for one run: split the PDF into files of about 10 pages and upload them separately |
| "La generazione è in corso: annullala prima di eliminarla." (The generation is running: cancel it before deleting) | Click **Annulla** on that row, then **Elimina** |
| "Importazione non riuscita." (Import failed) | The message below it gives the reason. Check that the file is a `.sbobina.zip` exported by Transcriber and that it was not damaged while copying |
| macOS: "Permission denied" or "Operation not permitted" | Make sure you typed `bash avvia.sh` and not `./avvia.sh` |
| An error appears in the window and the program stops | Take a photo of the screen and send it to whoever gave you the program, or open an issue at https://github.com/AndreaBonn/speech-to-text/issues (issues need a free GitHub account) |
| The transcript has many wrong words | Record closer to the lecturer; check the yellow words; try the automatic correction |
