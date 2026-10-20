// Human-facing terminology only. Do not apply this to filenames, URLs or commands.
export function studentText(value){
 return value
  .replace('DE:310 und DE:311 mit Boxen und Crops','DE:310 und DE:311 mit Bildbeispielen')
  .replace('Dobel: keine Box → kein Schild-Crop','Dobel: keine Box → kein Bildausschnitt')
  .replace('Klassifikation mit geprüften Crops neu lernen','Mit geprüften Bildausschnitten nachtrainieren')
  .replace('Crop\nWelcher Ausschnitt?','Bildausschnitt\nAus der Box')
  .replace('Box stimmt, Klasse falsch → Crops, Klasseninventar und Klassifikator prüfen','Box stimmt, Klasse falsch → Bildausschnitt, Klassen und Klassifikator prüfen')
  .replace('Definierte Crop-Ränder','Feste Ränder')
  .replace('Neue Klassen: Crops','Neue Klassen:\nBildausschnitte')
  .replace('3.015 zu 3.010 richtige von denselben 3.029 alten Crops','3.015 zu 3.010 richtig / 3.029 Bildausschnitte')
  .replace('Kleiner Ortstafeltest (3 + 12 Crops). Altbestand: rückblickender Vergleich.\nDer Kandidat erhält wegen der Regression keine Freigabe.','Ortstafeltest: 3 DE:310- und 12 DE:311-Bildausschnitte. Altbestand: rückblickend.\nWegen Regression keine Freigabe.')
  .replaceAll('Schild-Crops','Bildausschnitte')
  .replaceAll('Schild-Crop','Bildausschnitt')
  .replaceAll('Crop-Test','Test mit Bildausschnitten')
  .replace(/\bCrops\b/g,'Bildausschnitte')
  .replace(/\bCrop\b/g,'Bildausschnitt');
}
