"use client";

import { useEffect, useState } from "react";
import styles from "./page.module.css";

export default function Home() {
  const [wordPairs, setWordPairs] = useState<{ ja: string; en: string }[]>([]);
  const [index, setIndex] = useState(0);
  const [userAnswer, setUserAnswer] = useState("");
  const [isStarted, setIsStarted] = useState(false); // Track if the app is started

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

  const startApp = () => {
    setIsStarted(true);
  };

  const handleSubmit = () => {
    if (userAnswer.trim() === wordPairs[index].ja) {
      alert("Correct!");
      setIndex((prevIndex) => (prevIndex + 1) % wordPairs.length);
    } else {
      alert(`Incorrect - the correct answer was ${wordPairs[index].ja}`);
    }
    setUserAnswer(""); // Clear the input field after submission
  };

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        {!isStarted ? (
          <button onClick={startApp}>START</button> // Button to start the app
        ) : (
          wordPairs.length > 0 && (
            <>
              <h1>読</h1>
              <h2>&quot;{wordPairs[index].en}&quot;</h2>
              <input
                autoFocus
                type="text"
                value={userAnswer}
                onChange={(e) => setUserAnswer(e.target.value)}
                placeholder="Your answer"
                lang="ja"
                inputMode="text"
              />
              <button onClick={handleSubmit}>CHECK</button>
            </>
          )
        )}
      </main>
    </div>
  );
}
