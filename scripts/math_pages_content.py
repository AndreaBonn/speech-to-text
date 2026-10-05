"""Ten synthetic Italian study pages with formulas for the V10 OCR measure (T060).

Each page is a title and paragraphs; a paragraph is a sequence of plain text
strings and formulas, written ("i", latex) for inline and ("d", latex) for a
formula on its own line. The same LaTeX is the ground truth for scoring.
"""

Segment = str | tuple[str, str]
Page = tuple[str, tuple[tuple[Segment, ...], ...]]

PAGES: tuple[Page, ...] = (
    (
        "Limiti e derivate",
        (
            (
                "Il limite notevole ",
                ("i", r"\lim_{x \to 0} \frac{\sin x}{x} = 1"),
                " si usa spesso negli esercizi d'esame.",
            ),
            (
                "La derivata di una funzione nel punto ",
                ("i", "x_0"),
                " è definita come",
            ),
            (("d", r"f'(x_0) = \lim_{h \to 0} \frac{f(x_0 + h) - f(x_0)}{h}"),),
            (
                "Per il prodotto vale ",
                ("i", r"(fg)' = f'g + fg'"),
                ", mentre per il quoziente bisogna ricordare il segno meno.",
            ),
            (("d", r"\left(\frac{f}{g}\right)' = \frac{f'g - fg'}{g^2}"),),
        ),
    ),
    (
        "Integrali definiti",
        (
            ("Il teorema fondamentale del calcolo afferma che",),
            (("d", r"\int_a^b f(x) \, dx = F(b) - F(a)"),),
            (
                "dove ",
                ("i", "F"),
                " è una primitiva di ",
                ("i", "f"),
                ". Ad esempio l'area sotto la parabola è",
            ),
            (("d", r"\int_0^2 x^2 \, dx = \frac{8}{3}"),),
            (
                "Per sostituzione si pone ",
                ("i", r"t = g(x)"),
                " e ",
                ("i", r"dt = g'(x) \, dx"),
                ".",
            ),
        ),
    ),
    (
        "Serie numeriche",
        (
            (
                "La serie geometrica di ragione ",
                ("i", "q"),
                " converge se ",
                ("i", r"|q| < 1"),
                ":",
            ),
            (("d", r"\sum_{n=0}^{\infty} q^n = \frac{1}{1 - q}"),),
            (
                "La serie armonica invece diverge, anche se il termine generale ",
                ("i", r"\frac{1}{n}"),
                " tende a zero.",
            ),
            (("d", r"\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}"),),
        ),
    ),
    (
        "Matrici e sistemi lineari",
        (
            ("Data la matrice",),
            (("d", r"A = \begin{pmatrix} 2 & 1 \\ 1 & 3 \end{pmatrix}"),),
            (
                "il suo determinante è ",
                ("i", r"\det A = 2 \cdot 3 - 1 \cdot 1 = 5"),
                ", quindi il sistema ",
                ("i", r"A\mathbf{x} = \mathbf{b}"),
                " ha una sola soluzione.",
            ),
            (
                "L'inversa si ottiene come ",
                ("i", r"A^{-1} = \frac{1}{\det A} \operatorname{adj}(A)"),
                ".",
            ),
        ),
    ),
    (
        "Probabilità",
        (
            (
                "Per due eventi indipendenti vale ",
                ("i", r"P(A \cap B) = P(A) \, P(B)"),
                ".",
            ),
            ("La probabilità condizionata è definita da",),
            (("d", r"P(A \mid B) = \frac{P(A \cap B)}{P(B)}"),),
            ("e il teorema di Bayes la rovescia:",),
            (("d", r"P(B \mid A) = \frac{P(A \mid B) \, P(B)}{P(A)}"),),
        ),
    ),
    (
        "Statistica descrittiva",
        (
            (
                "La media campionaria di ",
                ("i", "n"),
                " osservazioni è",
            ),
            (("d", r"\bar{x} = \frac{1}{n} \sum_{i=1}^{n} x_i"),),
            ("e la varianza campionaria corretta è",),
            (("d", r"s^2 = \frac{1}{n-1} \sum_{i=1}^{n} (x_i - \bar{x})^2"),),
            (
                "Lo scarto quadratico medio è ",
                ("i", r"s = \sqrt{s^2}"),
                ", nella stessa unità dei dati.",
            ),
        ),
    ),
    (
        "Cinematica",
        (
            ("Nel moto uniformemente accelerato la posizione è",),
            (("d", r"x(t) = x_0 + v_0 t + \frac{1}{2} a t^2"),),
            ("e la velocità cresce linearmente: ", ("i", r"v(t) = v_0 + a t"), "."),
            (
                "Eliminando il tempo si ottiene ",
                ("i", r"v^2 = v_0^2 + 2a(x - x_0)"),
                ", utile quando il tempo non è noto.",
            ),
        ),
    ),
    (
        "Termodinamica",
        (
            ("Il primo principio si scrive ", ("i", r"\Delta U = Q - L"), "."),
            ("Per un gas perfetto vale l'equazione di stato",),
            (("d", r"pV = nRT"),),
            ("e in una trasformazione isoterma il lavoro è",),
            (("d", r"L = nRT \ln \frac{V_f}{V_i}"),),
            ("Il rendimento di Carnot è ", ("i", r"\eta = 1 - \frac{T_C}{T_H}"), "."),
        ),
    ),
    (
        "Elettromagnetismo",
        (
            ("La forza di Coulomb fra due cariche è",),
            (("d", r"F = \frac{1}{4\pi\varepsilon_0} \frac{q_1 q_2}{r^2}"),),
            ("La legge di Gauss collega il flusso del campo alla carica interna:",),
            (("d", r"\oint_S \mathbf{E} \cdot d\mathbf{A} = \frac{Q}{\varepsilon_0}"),),
            ("In un circuito resistivo vale ", ("i", r"V = RI"), "."),
        ),
    ),
    (
        "Economia: interesse composto",
        (
            (
                "Un capitale di 1000 $ investito al 5% annuo cresce come ",
                ("i", r"C_n = C_0 (1 + r)^n"),
                ".",
            ),
            ("Dopo dieci anni si ottiene",),
            (("d", r"C_{10} = 1000 \cdot 1{,}05^{10}"),),
            (
                "cioè circa 1629 $, una cifra da confrontare con l'",
                ("it", "inflazione"),
                " del periodo.",
            ),
        ),
    ),
)
