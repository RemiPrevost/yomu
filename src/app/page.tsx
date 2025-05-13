"use client";

import React, { useEffect, useState, useCallback } from "react";
import styles from "./page.module.css";
import Batch from "./batch/batch";

export default function Home() {
  const [wordPairs, setWordPairs] = useState<{ en: string; id: string; ja: string;  }[]>([]);
  const [isStarted, setIsStarted] = useState(false); // Track if the app is started
  const [batch, setBatch] = useState<{ en: string; id: string; ja: string; }[]>([]);
  const [answerLogs, setAnswerLogs] = useState<{ id: string; date: Date; correct: boolean; mistake: string | undefined }[]>([]); // State to store logs

  useEffect(() => {
    async function fetchWordPairs() {
      try {
        const response = await fetch("/api/words");
        const data = await response.json();
        setWordPairs(data);
      } catch (error) {
        console.error("Failed to fetch word pairs:", error);
      }
    }

    fetchWordPairs();
  }, []);

  const getNextBatch = useCallback(() => {
    const incorrectOrUnseen = wordPairs.filter((_, index) => {
      const log = [...answerLogs].reverse().find((log) => log.id === `${index}`); // Check the newest logs first
      return !log || !log.correct; // Include if not logged or logged as incorrect
    });
    return incorrectOrUnseen.slice(0, 10); // Take the first two items
  }, [wordPairs, answerLogs]);

  const collectAnswer = useCallback((id: string, correct: boolean, mistake: string | undefined) => {
    setAnswerLogs((prevLogs) => [
      ...prevLogs,
      { id, date: new Date(), correct, mistake },
    ]);
  }, []);

  useEffect(() => {
    console.log("Answer logs:", answerLogs);
  }, [answerLogs]);

  const startSession = useCallback(() => {
    setBatch(getNextBatch());
    setIsStarted(true);
  }, [getNextBatch]);

  const endSession = useCallback(() => {
    setIsStarted(false);
  }, []);

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>読</h1>
        {!isStarted ? (
          <button onClick={startSession}>Start session</button> // Button to start the app
        ) : (
          wordPairs.length > 0 && (
              <Batch
                batch={batch}
                collectAnswer={collectAnswer}
                endSession={endSession}
              />
          )
        )}
      </main>
    </div>
  );
}
