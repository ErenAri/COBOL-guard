       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEDGER01.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANS-IN ASSIGN TO "transactions.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT JOURNAL-OUT ASSIGN TO "ledger_journal.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT EXCEPTION-OUT ASSIGN TO "exception_report.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT TOTALS-OUT ASSIGN TO "reconcile_totals.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  TRANS-IN.
       01  TRANS-IN-LINE                 PIC X(88).

       FD  JOURNAL-OUT.
       01  JOURNAL-LINE                  PIC X(152).

       FD  EXCEPTION-OUT.
       01  EXCEPTION-LINE                PIC X(136).

       FD  TOTALS-OUT.
       01  TOTALS-LINE                   PIC X(94).

       WORKING-STORAGE SECTION.
       01  WS-EOF                        PIC X VALUE "N".
       01  WS-I                          PIC 9(7) COMP VALUE 0.
       01  WS-J                          PIC 9(7) COMP VALUE 0.
       01  WS-MATCH-INDEX                PIC 9(7) COMP VALUE 0.
       01  WS-MATCH-FOUND                PIC X VALUE "N".
       01  WS-ACCOUNT-INDEX              PIC 9(7) COMP VALUE 0.
       01  WS-POSTING-INDEX              PIC 9(7) COMP VALUE 0.

       01  WS-IN-TRANS.
           05 WS-IN-REQUEST-ID           PIC X(16).
           05 WS-IN-OPERATION            PIC X(8).
           05 WS-IN-ORIGINAL-REQUEST-ID  PIC X(16).
           05 WS-IN-ACCOUNT-ID           PIC X(12).
           05 WS-IN-AMOUNT-TEXT          PIC X(14).
           05 WS-IN-BUSINESS-DATE        PIC X(8).
           05 WS-IN-EVENT-TIME           PIC X(14).
       01  WS-IN-AMOUNT                  PIC S9(13) VALUE 0.

       01  WS-ACCOUNT-MAX                PIC 9(7) COMP VALUE 200000.
       01  WS-PROCESSED-MAX              PIC 9(7) COMP VALUE 400000.
       01  WS-POSTING-MAX                PIC 9(7) COMP VALUE 400000.
       01  WS-ACCOUNT-COUNT              PIC 9(7) COMP VALUE 0.
       01  WS-PROCESSED-COUNT            PIC 9(7) COMP VALUE 0.
       01  WS-POSTING-COUNT              PIC 9(7) COMP VALUE 0.

       01  WS-ACCOUNTS.
           05 WS-ACCOUNT-ENTRY OCCURS 200000 TIMES.
               10 WS-ACCOUNT-ID-TBL      PIC X(12).
               10 WS-ACCOUNT-BALANCE     PIC S9(13) VALUE 0.

       01  WS-PROCESSED.
           05 WS-PROCESSED-ENTRY OCCURS 400000 TIMES.
               10 WS-PROCESSED-REQUEST-ID PIC X(16).

       01  WS-POSTINGS.
           05 WS-POSTING-ENTRY OCCURS 400000 TIMES.
               10 WS-POSTING-REQUEST-ID  PIC X(16).
               10 WS-POSTING-ACCOUNT-ID  PIC X(12).
               10 WS-POSTING-AMOUNT      PIC S9(13) VALUE 0.
               10 WS-POSTING-REVERSED    PIC X VALUE "N".

       01  WS-SEQUENCE-NO                PIC 9(10) VALUE 0.
       01  WS-BUSINESS-DATE              PIC X(8) VALUE SPACES.
       01  WS-BEFORE-BALANCE             PIC S9(13) VALUE 0.
       01  WS-AFTER-BALANCE              PIC S9(13) VALUE 0.
       01  WS-AMOUNT-EFFECT              PIC S9(13) VALUE 0.
       01  WS-REVERSE-AMOUNT             PIC S9(13) VALUE 0.

       01  WS-STATUS                     PIC X(18).
       01  WS-AUDIT-EVENT                PIC X(22).
       01  WS-DETAIL                     PIC X(80).

       01  WS-TOTAL-POST-CENTS           PIC S9(13) VALUE 0.
       01  WS-TOTAL-REVERSE-CENTS        PIC S9(13) VALUE 0.
       01  WS-NET-DELTA-CENTS            PIC S9(13) VALUE 0.
       01  WS-CLOSING-TOTAL-CENTS        PIC S9(13) VALUE 0.
       01  WS-RECORDS-PROCESSED          PIC 9(10) VALUE 0.
       01  WS-APPLIED-RECORDS            PIC 9(10) VALUE 0.
       01  WS-EXCEPTION-COUNT            PIC 9(10) VALUE 0.

       01  WS-JOURNAL-REC.
           05 WS-JR-SEQUENCE-NO          PIC 9(10).
           05 WS-JR-BUSINESS-DATE        PIC X(8).
           05 WS-JR-ACCOUNT-ID           PIC X(12).
           05 WS-JR-REQUEST-ID           PIC X(16).
           05 WS-JR-OPERATION            PIC X(8).
           05 WS-JR-ORIGINAL-REQUEST-ID  PIC X(16).
           05 WS-JR-AMOUNT-CENTS         PIC +9(13).
           05 WS-JR-BEFORE-CENTS         PIC +9(13).
           05 WS-JR-AFTER-CENTS          PIC +9(13).
           05 WS-JR-STATUS               PIC X(18).
           05 WS-JR-AUDIT-EVENT          PIC X(22).

       01  WS-EXCEPTION-REC.
           05 WS-EX-BUSINESS-DATE        PIC X(8).
           05 WS-EX-ACCOUNT-ID           PIC X(12).
           05 WS-EX-REQUEST-ID           PIC X(16).
           05 WS-EX-ERROR-CODE           PIC X(20).
           05 WS-EX-DETAIL               PIC X(80).

       01  WS-TOTALS-REC.
           05 WS-TR-BUSINESS-DATE        PIC X(8).
           05 WS-TR-TOTAL-POST           PIC +9(13).
           05 WS-TR-TOTAL-REVERSE        PIC +9(13).
           05 WS-TR-NET-DELTA            PIC +9(13).
           05 WS-TR-CLOSING-TOTAL        PIC +9(13).
           05 WS-TR-RECORDS-PROCESSED    PIC 9(10).
           05 WS-TR-APPLIED-RECORDS      PIC 9(10).
           05 WS-TR-EXCEPTION-COUNT      PIC 9(10).

       01  WS-YES                        PIC X VALUE "Y".
       01  WS-NO                         PIC X VALUE "N".

       PROCEDURE DIVISION.
       MAIN.
           OPEN INPUT TRANS-IN
           OPEN OUTPUT JOURNAL-OUT
           OPEN OUTPUT EXCEPTION-OUT
           OPEN OUTPUT TOTALS-OUT
           PERFORM UNTIL WS-EOF = WS-YES
               READ TRANS-IN
                   AT END
                       MOVE WS-YES TO WS-EOF
                   NOT AT END
                       PERFORM PROCESS-TRANS
               END-READ
           END-PERFORM
           PERFORM WRITE-TOTALS
           CLOSE TRANS-IN
           CLOSE JOURNAL-OUT
           CLOSE EXCEPTION-OUT
           CLOSE TOTALS-OUT
           GOBACK.

       PROCESS-TRANS.
           ADD 1 TO WS-SEQUENCE-NO
           ADD 1 TO WS-RECORDS-PROCESSED
           MOVE TRANS-IN-LINE(1:16) TO WS-IN-REQUEST-ID
           MOVE TRANS-IN-LINE(17:8) TO WS-IN-OPERATION
           MOVE TRANS-IN-LINE(25:16) TO WS-IN-ORIGINAL-REQUEST-ID
           MOVE TRANS-IN-LINE(41:12) TO WS-IN-ACCOUNT-ID
           MOVE TRANS-IN-LINE(53:14) TO WS-IN-AMOUNT-TEXT
           MOVE TRANS-IN-LINE(67:8) TO WS-IN-BUSINESS-DATE
           MOVE TRANS-IN-LINE(75:14) TO WS-IN-EVENT-TIME
           MOVE WS-IN-AMOUNT-TEXT TO WS-IN-AMOUNT

           IF WS-BUSINESS-DATE = SPACES
               MOVE WS-IN-BUSINESS-DATE TO WS-BUSINESS-DATE
           END-IF

           MOVE ZERO TO WS-AMOUNT-EFFECT
           MOVE ZERO TO WS-REVERSE-AMOUNT
           PERFORM FIND-OR-CREATE-ACCOUNT
           MOVE WS-BEFORE-BALANCE TO WS-AFTER-BALANCE
           MOVE SPACES TO WS-STATUS
           MOVE SPACES TO WS-AUDIT-EVENT
           MOVE SPACES TO WS-DETAIL

           IF WS-IN-BUSINESS-DATE NOT = WS-BUSINESS-DATE
               MOVE "BUSINESS_DATE_MISMATCH" TO WS-STATUS
               MOVE "TXN_REJECTED" TO WS-AUDIT-EVENT
               STRING "expected=" DELIMITED BY SIZE
                      WS-BUSINESS-DATE DELIMITED BY SIZE
                      " actual=" DELIMITED BY SIZE
                      WS-IN-BUSINESS-DATE DELIMITED BY SIZE
                   INTO WS-DETAIL
               END-STRING
               PERFORM WRITE-EXCEPTION
           ELSE
               IF WS-IN-OPERATION(1:4) = "POST"
                   PERFORM HANDLE-POST
               ELSE
                   IF WS-IN-OPERATION(1:7) = "REVERSE"
                       PERFORM HANDLE-REVERSE
                   ELSE
                       MOVE "BAD_OPERATION" TO WS-STATUS
                       MOVE "TXN_REJECTED" TO WS-AUDIT-EVENT
                       STRING "operation=" DELIMITED BY SIZE
                              WS-IN-OPERATION DELIMITED BY SIZE
                           INTO WS-DETAIL
                       END-STRING
                       PERFORM WRITE-EXCEPTION
                   END-IF
               END-IF
           END-IF

           PERFORM WRITE-JOURNAL.

       HANDLE-POST.
           PERFORM FIND-PROCESSED
           IF WS-MATCH-FOUND = WS-YES
               MOVE "DUPLICATE_IGNORED" TO WS-STATUS
               MOVE "POST_DUPLICATE" TO WS-AUDIT-EVENT
           ELSE
               MOVE WS-IN-AMOUNT TO WS-AMOUNT-EFFECT
               COMPUTE WS-AFTER-BALANCE = WS-BEFORE-BALANCE + WS-AMOUNT-EFFECT
               MOVE WS-AFTER-BALANCE TO WS-ACCOUNT-BALANCE(WS-ACCOUNT-INDEX)
               PERFORM ADD-PROCESSED
               PERFORM ADD-POSTING
               MOVE "APPLIED" TO WS-STATUS
               MOVE "POST_APPLIED" TO WS-AUDIT-EVENT
               ADD WS-IN-AMOUNT TO WS-TOTAL-POST-CENTS
               ADD 1 TO WS-APPLIED-RECORDS
           END-IF.

       HANDLE-REVERSE.
           PERFORM FIND-PROCESSED
           IF WS-MATCH-FOUND = WS-YES
               MOVE "DUPLICATE_IGNORED" TO WS-STATUS
               MOVE "REVERSE_DUPLICATE" TO WS-AUDIT-EVENT
           ELSE
                   PERFORM FIND-POSTING
                   IF WS-MATCH-FOUND = WS-NO
                   MOVE "ORIG_NOT_FOUND" TO WS-STATUS
                   MOVE "REVERSE_REJECTED" TO WS-AUDIT-EVENT
                   STRING "original_request_id=" DELIMITED BY SIZE
                          WS-IN-ORIGINAL-REQUEST-ID DELIMITED BY SIZE
                       INTO WS-DETAIL
                   END-STRING
                   PERFORM ADD-PROCESSED
                   PERFORM WRITE-EXCEPTION
               ELSE
                   IF WS-POSTING-REVERSED(WS-POSTING-INDEX) = WS-YES
                       MOVE "ORIG_ALREADY_REVERSED" TO WS-STATUS
                       MOVE "REVERSE_REJECTED" TO WS-AUDIT-EVENT
                       STRING "original_request_id=" DELIMITED BY SIZE
                              WS-IN-ORIGINAL-REQUEST-ID DELIMITED BY SIZE
                           INTO WS-DETAIL
                       END-STRING
                       PERFORM ADD-PROCESSED
                       PERFORM WRITE-EXCEPTION
                   ELSE
                       IF WS-POSTING-ACCOUNT-ID(WS-POSTING-INDEX)
                           NOT = WS-IN-ACCOUNT-ID
                           MOVE "ACCOUNT_MISMATCH" TO WS-STATUS
                           MOVE "REVERSE_REJECTED" TO WS-AUDIT-EVENT
                           STRING "original_account=" DELIMITED BY SIZE
                                  WS-POSTING-ACCOUNT-ID(WS-POSTING-INDEX)
                                  DELIMITED BY SIZE
                               INTO WS-DETAIL
                           END-STRING
                           PERFORM ADD-PROCESSED
                           PERFORM WRITE-EXCEPTION
                       ELSE
                           MOVE WS-POSTING-AMOUNT(WS-POSTING-INDEX)
                               TO WS-REVERSE-AMOUNT
                           COMPUTE WS-AMOUNT-EFFECT = 0 - WS-REVERSE-AMOUNT
                           COMPUTE WS-AFTER-BALANCE =
                               WS-BEFORE-BALANCE + WS-AMOUNT-EFFECT
                           MOVE WS-AFTER-BALANCE
                               TO WS-ACCOUNT-BALANCE(WS-ACCOUNT-INDEX)
                           MOVE WS-YES
                               TO WS-POSTING-REVERSED(WS-POSTING-INDEX)
                           PERFORM ADD-PROCESSED
                           MOVE "APPLIED" TO WS-STATUS
                           MOVE "REVERSE_APPLIED" TO WS-AUDIT-EVENT
                           ADD WS-REVERSE-AMOUNT TO WS-TOTAL-REVERSE-CENTS
                           ADD 1 TO WS-APPLIED-RECORDS
                       END-IF
                   END-IF
               END-IF
           END-IF.

       FIND-OR-CREATE-ACCOUNT.
           MOVE ZERO TO WS-ACCOUNT-INDEX
           PERFORM VARYING WS-I FROM 1 BY 1
               UNTIL WS-I > WS-ACCOUNT-COUNT OR WS-ACCOUNT-INDEX > 0
               IF WS-ACCOUNT-ID-TBL(WS-I) = WS-IN-ACCOUNT-ID
                   MOVE WS-I TO WS-ACCOUNT-INDEX
               END-IF
           END-PERFORM
           IF WS-ACCOUNT-INDEX = 0
               ADD 1 TO WS-ACCOUNT-COUNT
               MOVE WS-ACCOUNT-COUNT TO WS-ACCOUNT-INDEX
               MOVE WS-IN-ACCOUNT-ID TO WS-ACCOUNT-ID-TBL(WS-ACCOUNT-INDEX)
               MOVE ZERO TO WS-ACCOUNT-BALANCE(WS-ACCOUNT-INDEX)
           END-IF
           MOVE WS-ACCOUNT-BALANCE(WS-ACCOUNT-INDEX) TO WS-BEFORE-BALANCE.

       FIND-PROCESSED.
           MOVE WS-NO TO WS-MATCH-FOUND
           PERFORM VARYING WS-I FROM 1 BY 1
               UNTIL WS-I > WS-PROCESSED-COUNT OR WS-MATCH-FOUND = WS-YES
               IF WS-PROCESSED-REQUEST-ID(WS-I) = WS-IN-REQUEST-ID
                   MOVE WS-YES TO WS-MATCH-FOUND
               END-IF
           END-PERFORM.

       ADD-PROCESSED.
           ADD 1 TO WS-PROCESSED-COUNT
           MOVE WS-IN-REQUEST-ID TO
               WS-PROCESSED-REQUEST-ID(WS-PROCESSED-COUNT).

       ADD-POSTING.
           ADD 1 TO WS-POSTING-COUNT
           MOVE WS-IN-REQUEST-ID TO WS-POSTING-REQUEST-ID(WS-POSTING-COUNT)
           MOVE WS-IN-ACCOUNT-ID TO WS-POSTING-ACCOUNT-ID(WS-POSTING-COUNT)
           MOVE WS-IN-AMOUNT TO WS-POSTING-AMOUNT(WS-POSTING-COUNT)
           MOVE WS-NO TO WS-POSTING-REVERSED(WS-POSTING-COUNT).

       FIND-POSTING.
           MOVE WS-NO TO WS-MATCH-FOUND
           MOVE ZERO TO WS-POSTING-INDEX
           PERFORM VARYING WS-I FROM 1 BY 1
               UNTIL WS-I > WS-POSTING-COUNT OR WS-MATCH-FOUND = WS-YES
               IF WS-POSTING-REQUEST-ID(WS-I) = WS-IN-ORIGINAL-REQUEST-ID
                   MOVE WS-YES TO WS-MATCH-FOUND
                   MOVE WS-I TO WS-POSTING-INDEX
               END-IF
           END-PERFORM.

       WRITE-JOURNAL.
           MOVE WS-SEQUENCE-NO TO WS-JR-SEQUENCE-NO
           MOVE WS-BUSINESS-DATE TO WS-JR-BUSINESS-DATE
           MOVE WS-IN-ACCOUNT-ID TO WS-JR-ACCOUNT-ID
           MOVE WS-IN-REQUEST-ID TO WS-JR-REQUEST-ID
           MOVE WS-IN-OPERATION TO WS-JR-OPERATION
           MOVE WS-IN-ORIGINAL-REQUEST-ID TO WS-JR-ORIGINAL-REQUEST-ID
           MOVE WS-AMOUNT-EFFECT TO WS-JR-AMOUNT-CENTS
           MOVE WS-BEFORE-BALANCE TO WS-JR-BEFORE-CENTS
           MOVE WS-AFTER-BALANCE TO WS-JR-AFTER-CENTS
           MOVE WS-STATUS TO WS-JR-STATUS
           MOVE WS-AUDIT-EVENT TO WS-JR-AUDIT-EVENT
           MOVE WS-JOURNAL-REC TO JOURNAL-LINE
           WRITE JOURNAL-LINE.

       WRITE-EXCEPTION.
           ADD 1 TO WS-EXCEPTION-COUNT
           MOVE WS-BUSINESS-DATE TO WS-EX-BUSINESS-DATE
           MOVE WS-IN-ACCOUNT-ID TO WS-EX-ACCOUNT-ID
           MOVE WS-IN-REQUEST-ID TO WS-EX-REQUEST-ID
           MOVE WS-STATUS TO WS-EX-ERROR-CODE
           MOVE WS-DETAIL TO WS-EX-DETAIL
           MOVE WS-EXCEPTION-REC TO EXCEPTION-LINE
           WRITE EXCEPTION-LINE.

       WRITE-TOTALS.
           MOVE ZERO TO WS-CLOSING-TOTAL-CENTS
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > WS-ACCOUNT-COUNT
               ADD WS-ACCOUNT-BALANCE(WS-I) TO WS-CLOSING-TOTAL-CENTS
           END-PERFORM
           COMPUTE WS-NET-DELTA-CENTS =
               WS-TOTAL-POST-CENTS - WS-TOTAL-REVERSE-CENTS
           MOVE WS-BUSINESS-DATE TO WS-TR-BUSINESS-DATE
           MOVE WS-TOTAL-POST-CENTS TO WS-TR-TOTAL-POST
           MOVE WS-TOTAL-REVERSE-CENTS TO WS-TR-TOTAL-REVERSE
           MOVE WS-NET-DELTA-CENTS TO WS-TR-NET-DELTA
           MOVE WS-CLOSING-TOTAL-CENTS TO WS-TR-CLOSING-TOTAL
           MOVE WS-RECORDS-PROCESSED TO WS-TR-RECORDS-PROCESSED
           MOVE WS-APPLIED-RECORDS TO WS-TR-APPLIED-RECORDS
           MOVE WS-EXCEPTION-COUNT TO WS-TR-EXCEPTION-COUNT
           MOVE WS-TOTALS-REC TO TOTALS-LINE
           WRITE TOTALS-LINE.
