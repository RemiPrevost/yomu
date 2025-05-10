"use client";

import clsx from "clsx";
import styles from "./wordPair.module.css";
import Input from "./input/input";

interface WordPairProps {
    active: boolean;
    answer?: string;
    en: string;
    handleFocus: (state: boolean) => void;
    isChecking: boolean;
    ja: string;
    setAnswer: (answer: string) => void;
}

export default function WordPair({
    active,
    answer = "",
    en,
    handleFocus,
    isChecking,
    ja,
    setAnswer,
}: WordPairProps) {
    return (
        <div className={clsx(
            styles["word-pair"],
            { [styles.active]: active || answer.length > 0 },
            { [styles.checking]: isChecking },
            { [styles.correct]: isChecking && answer === ja }
        )}>
            <div className={styles.row}>
                <div className={styles["left"]}>
                    {isChecking && (answer === ja ? "✅" : "❌")}
                    <h2>{en}</h2>
                </div>
                <Input
                    active={active}
                    answer={answer}
                    handleFocus={handleFocus}
                    setAnswer={setAnswer}
                />
            </div>
            {isChecking && answer !== ja && <h2>Correct answer: {ja}</h2>}
        </div>
    );
}
