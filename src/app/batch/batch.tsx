"use client";

import React, { useMemo, useCallback, useState } from "react";
import WordPair from "./wordPair/wordPair";
import styles from "./batch.module.css";
import clsx from "clsx";

interface BatchProps {
    batch: { en: string; id: string; ja: string; }[]; // Define the type for the batch prop
    collectAnswer: (id: string, correct: boolean, mistake: string | undefined) => void; // Function to collect answers
    endSession: () => void; // Function to end the session
}

export default function Batch({batch, collectAnswer, endSession}: BatchProps) {
    const [answers, setAnswers] = useState<Record<string, string>>({}); // Transform answers to an object
    const [index, setIndex] = useState<number | undefined>(undefined);
    const [isChecking, setIsCheching] = useState<boolean>(false);

    const setAnswer = useCallback((answer: string, id: string) => {
        setAnswers((prevAnswers) => ({
            ...prevAnswers,
            [id]: answer, // Use batch id as the key
        }));
    }, []);

    const handleFocus = useCallback((state: boolean, idx: number) => {
        setIndex(state ? idx : undefined); // Set the index when focused
    }, []);

    const isReadyToCheck = useMemo(() => {
        return Object.keys(answers).length === batch.length && Object.values(answers).every(answer => answer !== "");
    }, [answers, batch.length]);

    const areAllCorrect = useMemo(() => {
        return Object.keys(answers).length === batch.length && batch.every(pair => answers[pair.id] === pair.ja);
    }, [answers, batch]);

    const checkAnswers = useCallback(() => {
        setIsCheching(true);

        batch.forEach((pair) => {
            const isCorrect = answers[pair.id] === pair.ja;
            collectAnswer(pair.id, isCorrect, !isCorrect ? answers[pair.id] : undefined); // Collect the answer
        });
    }, [answers, batch, collectAnswer]);

    return (
        <div className={clsx(styles.batch)}>
            <div>
                {batch.map((pair, idx) => (
                    <React.Fragment key={`${pair.id}`}> {/* Add a unique key to the fragment */}
                        <WordPair
                            active={index === idx}
                            answer={answers[pair.id]} // Access answer by id
                            en={pair.en}
                            isChecking={isChecking}
                            handleFocus={state => handleFocus(state, idx)} // Set the index when clicked
                            ja={pair.ja} // Show the answer if provided
                            setAnswer={answer => setAnswer(answer, pair.id)} // Use id for setting answer
                        />
                    </React.Fragment>
                ))}
            </div>
            <div className={styles.footer}>
                {isReadyToCheck && !isChecking && (
                    <button onClick={checkAnswers}>Check now</button>
                )}
                {areAllCorrect && isChecking && (
                    <button className={styles["end-button"]} onClick={endSession}>
                        End session
                    </button>
                )}
            </div>
        </div>
    );
}
