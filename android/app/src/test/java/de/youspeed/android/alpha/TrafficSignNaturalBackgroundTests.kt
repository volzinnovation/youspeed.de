package de.youspeed.android.alpha
import org.junit.Assert.*
import org.junit.Test
class TrafficSignNaturalBackgroundTests {
 @Test fun vegetationIsNotAnUnreadPlateButPanelsDarknessAndSmallCropsRemainUnknown() {
  val w=160;val h=256;val p=IntArray(w*h) {index -> val x=index%w;val y=index/w
    (255 shl 24) or ((40+(x*13+y*17)%70) shl 16) or ((120+(x*11+y*7)%90) shl 8) or (20+(x*5+y*23)%30)}
  assertTrue(TrafficSignPlateDetector.naturalBackground(w,h,p))
  assertEquals("plain",TrafficSignPlateDetector.scan(w,h,p).status)
  for(y in 155 until 195)for(x in 30 until 130)p[y*w+x]=0xffe6e6e6.toInt()
  assertFalse(TrafficSignPlateDetector.naturalBackground(w,h,p))
  assertNotEquals("plain",TrafficSignPlateDetector.scan(w,h,p).status)
  assertFalse(TrafficSignPlateDetector.naturalBackground(w,h,IntArray(w*h)))
  assertFalse(TrafficSignPlateDetector.naturalBackground(40,64,IntArray(40*64){0xff787878.toInt()}))
 }
}
