"use client";

import React, { useMemo } from "react";
import { useCallback, useState } from "react";
import WordPair from "./wordPair/wordPair";
import styles from "./batch.module.css";
import clsx from "clsx";

interface BatchProps {
    batch: { ja: string; en: string }[]; // Define the type for the batch prop
}

export default function Batch({batch}: BatchProps) {
    const [answers, setAnswers] = useState<string[]>([]); // Track the answers
    const [index, setIndex] = useState<number | undefined>(undefined);
    const [isChecking, setIsCheching] = useState<boolean>(false);
    

    const setAnswer = useCallback((answer: string, index: number) => {
        setAnswers((prevAnswers) => {
            const newAnswers = [...prevAnswers];
            newAnswers[index] = answer; // Store the user's answer
            return newAnswers;
        });
    }, []);

    const handleFocus = useCallback((state: boolean, idx: number) => {
        setIndex(state ? idx : undefined); // Set the index when focused
    }, []);

    const isReadyToCheck = useMemo(() => {
        return answers.length === batch.length && answers.every(answer => answer !== "");
    }, [answers, batch.length]);

    const areAllCorrect = useMemo(() => {
        return answers.length === batch.length && answers.every((answer, idx) => answer === batch[idx].ja);
    }, [answers, batch]);

    return (
        <div className={clsx(styles.batch)}>
            <div>
                {batch.map((pair, idx) => (
                    <React.Fragment key={`${pair.en}-${idx}`}> {/* Add a unique key to the fragment */}
                    <WordPair
                        active={index === idx}
                        answer={answers[idx]}
                        en={pair.en}
                        isChecking={isChecking}
                        handleFocus={state => handleFocus(state, idx)} // Set the index when clicked
                        ja={pair.ja} // Show the answer if provided
                        setAnswer={answer => setAnswer(answer, idx)}
                    />
                    </React.Fragment>
                ))}
            </div>
            <div className={styles.footer}>
                {isReadyToCheck && !isChecking && (
                    <button onClick={() => setIsCheching(true)}>Check now</button>
                )}
                {areAllCorrect && isChecking && (
                    <button className={styles["end-button"]} onClick={() => {}}>
                        End session
                    </button>
                )}
            </div>
        </div>
    );
}
