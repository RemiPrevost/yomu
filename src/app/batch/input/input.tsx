"use client";

import { useCallback, useState } from "react";
import styles from "./input.module.css";

interface InputProps {
    handleSubmit: (answer: string) => void;
    initialAnswer?: string;
}

export default function Input({ handleSubmit, initialAnswer = "" }: InputProps) {
    const [answer, setAnswer] = useState(initialAnswer);

    const onClick = useCallback(() => {
        handleSubmit(answer);
    }, [answer, handleSubmit]);

    return (
        <div className={styles["input"]}>
            <input
                autoFocus
                type="text"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Your answer"
                lang="ja"
                inputMode="text"
            />
            <button onClick={onClick}>Submit</button>
        </div>
    );
}
