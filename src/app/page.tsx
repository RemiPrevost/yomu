"use client";

import React, { useEffect, useState } from "react";
import styles from "./page.module.css";
import Batch from "./batch/batch";

export default function Home() {
  const [wordPairs, setWordPairs] = useState<{ ja: string; en: string }[]>([]);
  const [isStarted, setIsStarted] = useState(false); // Track if the app is started
  const [batch, setBatch] = useState<{ ja: string; en: string }[]>([]);
  

  useEffect(() => {
    async function fetchWordPairs() {
      try {
        const response = await fetch("/api/words");
        const data = await response.json();
        setWordPairs(data);
        setBatch(data.slice(0, 10)); // Set the initial batch of word pairs
      } catch (error) {
        console.error("Failed to fetch word pairs:", error);
      }
    }

    fetchWordPairs();
  }, []);

  const startApp = () => {
    setIsStarted(true);
  };

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <h1>読</h1> 
        {!isStarted ? (
          <button onClick={startApp}>START</button> // Button to start the app
        ) : (
          wordPairs.length > 0 && (
              <Batch batch={batch} />
          )
        )}
      </main>
    </div>
  );
}
