import { NextApiRequest, NextApiResponse } from 'next';
import fs from 'fs';
import path from 'path';
import csvParser from 'csv-parser';

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const filePath = path.join(process.cwd(), 'data', 'extracted_pairs.csv');

  try {
    const results: { en: string; id: string; ja: string; }[] = [];

    fs.createReadStream(filePath)
      .pipe(csvParser())
      .on('data', (data) => results.push({ en: data.en, id: data.id, ja: data.ja }))
      .on('end', () => {
        res.status(200).json(results);
      });
  } catch (error) {
    res.status(500).json({ error: 'Failed to read the CSV file' });
  }
}
