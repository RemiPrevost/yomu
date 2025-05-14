import { useState, useCallback, useMemo } from "react";

export interface WordPairType {
  en: string;
  id: string;
  ja: string;
}

async function postAnswerLog(id: string, isCorrect: boolean, wrongAnswer?: string) {
  await fetch("/api/answerLogs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, isCorrect, wrongAnswer }),
  });
}

export function useBatch(batch: WordPairType[]) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [index, setIndex] = useState<number | undefined>(undefined);
  const [isChecking, setIsCheching] = useState<boolean>(false);

  const setAnswer = useCallback((answer: string, id: string) => {
    setAnswers((prevAnswers) => ({
      ...prevAnswers,
      [id]: answer,
    }));
  }, []);

  const handleFocus = useCallback((state: boolean, idx: number) => {
    setIndex(state ? idx : undefined);
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
      postAnswerLog(pair.id, isCorrect, !isCorrect ? answers[pair.id] : undefined);
    });
  }, [answers, batch]);

  return {
    answers,
    setAnswer,
    index,
    isChecking,
    handleFocus,
    isReadyToCheck,
    areAllCorrect,
    checkAnswers,
  };
}
