       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEDGER01.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANS-IN ASSIGN TO "transactions.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT JOURNAL-OUT ASSIGN TO "ledger_journal.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  TRANS-IN.
       01  TRANS-IN-LINE                 PIC X(143).

       FD  JOURNAL-OUT.
       01  JOURNAL-LINE                  PIC X(143).

       WORKING-STORAGE SECTION.
       01  WS-EOF                        PIC X VALUE "N".

       PROCEDURE DIVISION.
       MAIN.
           PERFORM UNTIL WS-EOF = "Y"
               READ TRANS-IN
                   AT END
                       MOVE "Y" TO WS-EOF
                   NOT AT END
                       MOVE TRANS-IN-LINE TO JOURNAL-LINE
                       WRITE JOURNAL-LINE
               END-READ
           END-PERFORM
           GOBACK.
