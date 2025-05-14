"use client";

import React, { useState, useCallback } from "react";
import styles from "./page.module.css";
import Batch from "./batch/batch";

export default function Home() {
  const [isStarted, setIsStarted] = useState(false); // Track if the app is started
  const [batch, setBatch] = useState<{ en: string; id: string; ja: string; }[]>([]);

  const startSession = async () => {
    try {
      const response = await fetch("/api/words");
      const data = await response.json();
      setBatch(data);
      setIsStarted(true);
    } catch (error) {
      console.error("Failed to fetch word pairs:", error);
    }
  };

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
          batch.length > 0 && (
              <Batch
                batch={batch}
                endSession={endSession}
              />
          )
        )}
      </main>
    </div>
  );
}
