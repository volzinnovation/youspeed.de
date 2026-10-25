package de.youspeed.android.alpha
import org.junit.Assert.*
import org.junit.Test
class TripStopPromptTests {
 @Test fun delayContinueRearmAndFreshness() {
  val p=TripStopPromptPolicy()
  for(t in 0..30)p.observe(0.0,t.toDouble(),true,true)
  assertFalse(p.visible(30.0));p.observe(10.0,31.0,true,true)
  for(t in 32..46)p.observe(0.0,t.toDouble(),true,true)
  assertFalse(p.visible(46.0));p.observe(0.0,47.0,true,true)
  assertTrue(p.visible(47.0));assertFalse(p.visible(51.0));p.continueTrip()
  for(t in 48..70)p.observe(0.0,t.toDouble(),true,true)
  assertFalse(p.visible(70.0));p.observe(4.0,71.0,true,true)
  for(t in 72..87)p.observe(0.0,t.toDouble(),true,true)
  assertTrue(p.visible(87.0));p.observe(1.0,88.0,true,true);assertFalse(p.visible(88.0))
 }
 @Test fun estimatesAndDigitReplacement() {
  assertEquals(123454,TripOdometer.estimate(123450.0,4405.0));assertEquals(0,TripOdometer.estimate(null,4405.0))
  assertEquals(999999,TripOdometer.estimate(999999.0,9000.0));assertEquals(129456,TripOdometer.replacingDigit(123456,2,9))
 }
}
