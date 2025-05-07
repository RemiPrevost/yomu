"use client";

import React, { useMemo } from "react";
import { useCallback, useState } from "react";
import WordPair from "./wordPair/wordPair";
import Input from "./input/input";
import styles from "./batch.module.css";
import clsx from "clsx";

interface BatchProps {
    batch: { ja: string; en: string }[]; // Define the type for the batch prop
}

export default function Batch({batch}: BatchProps) {
    const [answers, setAnswers] = useState<string[]>([]); // Track the answers
    const [index, setIndex] = useState<number>(0);
    const [isChecking, setIsCheching] = useState<boolean>(false);
    

    const handleSubmit = useCallback((answer: string) => {
        setIndex((prevIndex) => (prevIndex + 1)); // Move to the next word pair
        setAnswers((prevAnswers) => {
            const newAnswers = [...prevAnswers];
            newAnswers[index] = answer; // Store the user's answer
            return newAnswers;
        });
    }, [index]);

    const isReadyToCheck = useMemo(() => {
        return answers.length === batch.length && answers.every(answer => answer !== "");
    }, [answers, batch.length]);

    return (
        <div className={clsx(styles.batch)}>
            {batch.map((pair, idx) => (
                <React.Fragment key={`${pair.en}-${idx}`}> {/* Add a unique key to the fragment */}
                  <WordPair
                    active={index === idx}
                    answer={answers[idx]}
                    en={pair.en}
                    isChecking={isChecking}
                    ja={pair.ja} // Show the answer if provided
                    onClick={() => setIndex(idx)} // Set the index when clicked
                  />
                  {idx === index && (
                    <Input
                      handleSubmit={handleSubmit}
                      initialAnswer={answers[idx]} // Pass the initial
                    />
                  )}
                </React.Fragment>
              ))}
            {isReadyToCheck && (
                <button onClick={() => setIsCheching(true)}>Check them all</button>
            )}
        </div>
    );
}
