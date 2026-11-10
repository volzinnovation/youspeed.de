"""Exercise the Java contract actually called by the isolated native harness."""
from pathlib import Path
import subprocess


def test_expanded_java_contract_accepts_142_and_rejects_mismatched_outputs(tmp_path):
    root = Path(__file__).resolve().parents[2]
    jdk = Path('/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin')
    source = root / 'scripts/android/classifier-benchmark/app/src/main/java/de/youspeed/classifierbenchmark/ClassContract.java'
    probe = tmp_path / 'ContractProbe.java'
    probe.write_text('''package de.youspeed.classifierbenchmark;
import java.util.Arrays;
public class ContractProbe {
  static String[] labels(int n) {
    String[] out = new String[n];
    for (int i=0;i<n;i++) out[i]="class:"+i;
    if(n>=136) {out[134]="city:start";out[135]="city:end";}
    return out;
  }
  static void rejects(Runnable action) {
    try {action.run();} catch(IllegalArgumentException expected) {return;}
    throw new AssertionError("Invalid classifier contract accepted");
  }
  public static void main(String[] args) {
    String[] old=labels(136), expanded=labels(142);
    ClassContract.validateLabels(labels(134));
    ClassContract.validateLabels(old);
    ClassContract.validateLabels(expanded);
    ClassContract.validateSharedPrefix(old, expanded);
    ClassContract.validateSharedPrefix(expanded, old);
    ClassContract.validateOutputShape(new int[]{1,142},142);
    rejects(()->ClassContract.validateOutputShape(new int[]{1,136},142));
    rejects(()->ClassContract.validateOutputShape(new int[]{2,142},142));
    rejects(()->ClassContract.validateOutputShape(new int[]{142},142));
    rejects(()->ClassContract.validateLabels(labels(135)));
    String[] wrongCity=expanded.clone();wrongCity[134]="wrong:city";
    rejects(()->ClassContract.validateLabels(wrongCity));
    String[] wrongPrefix=expanded.clone();wrongPrefix[80]="changed:old";
    rejects(()->ClassContract.validateSharedPrefix(old,wrongPrefix));
    String[] duplicate=expanded.clone();duplicate[141]=duplicate[140];
    rejects(()->ClassContract.validateLabels(duplicate));
  }
}''')
    subprocess.run([str(jdk/'javac'), '-d', str(tmp_path), str(source), str(probe)], check=True, capture_output=True)
    subprocess.run([str(jdk/'java'), '-cp', str(tmp_path), 'de.youspeed.classifierbenchmark.ContractProbe'], check=True, capture_output=True)
