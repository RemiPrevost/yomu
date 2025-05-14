"use client";

import React from "react";
import WordPair from "./wordPair/wordPair";
import styles from "./batch.module.css";
import clsx from "clsx";
import { useBatch } from "./useBatch";

interface BatchProps {
    batch: { en: string; id: string; ja: string; }[]; // Define the type for the batch prop
    endSession: () => void; // Function to end the session
}

export default function Batch({batch, endSession}: BatchProps) {
    const {
        answers,
        setAnswer,
        index,
        isChecking,
        handleFocus,
        isReadyToCheck,
        areAllCorrect,
        checkAnswers,
    } = useBatch(batch);

    return (
        <div className={clsx(styles.batch)}>
            <div>
                {batch.map((pair, idx) => (
                    <React.Fragment key={`${pair.id}`}>
                        <WordPair
                            active={index === idx}
                            answer={answers[pair.id]}
                            en={pair.en}
                            isChecking={isChecking}
                            handleFocus={state => handleFocus(state, idx)}
                            ja={pair.ja}
                            setAnswer={answer => setAnswer(answer, pair.id)}
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
