"use client";

import { useCallback } from "react";
import styles from "./input.module.css";
import clsx from "clsx";

interface InputProps {
    active: boolean;
    answer?: string;
    handleFocus: (state: boolean) => void;
    setAnswer: (answer: string) => void;
}

export default function Input({ active, answer = "", handleFocus, setAnswer }: InputProps) {
    const onFocus = useCallback(() => {
        handleFocus(true);
    }, [handleFocus]);

    const onBlur = useCallback(() => {
        handleFocus(false);
    }, [handleFocus]);

    return (
        <input
            className={clsx(styles["input"], { [styles.active]: active },)}
            inputMode="text"
            lang="ja"
            onBlur={onBlur}
            onChange={(e) => setAnswer(e.target.value)}
            onFocus={onFocus}
            placeholder="Your answer"
            type="text"
            value={answer}
        />
    );
}
