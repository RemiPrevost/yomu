"use client";

import clsx from "clsx";
import styles from "./wordPair.module.css";

interface WordPairProps {
    active: boolean;
    answer?: string;
    en: string;
    isChecking: boolean;
    ja: string;
    onClick: () => void;
}

export default function WordPair({active, answer = "", en, isChecking, ja, onClick }: WordPairProps) {
    return (
        <div className={clsx(styles["word-pair"], { [styles.active]: active && !isChecking })}>
            <button onClick={onClick}>
                <div className={styles["left"]}>
                    <h2>{en}</h2>
                    {isChecking && (answer === ja ? "✅" : "❌")}
                </div>
                <h2>{answer}</h2>
            </button>
            {isChecking && answer !== ja && <h2>{ja}</h2>}
        </div>
    );
}
