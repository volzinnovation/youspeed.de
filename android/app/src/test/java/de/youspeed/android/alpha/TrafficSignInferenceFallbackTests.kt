package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test

class TrafficSignInferenceFallbackTests {
    private class Resource(val name: String, val closeFailure: RuntimeException? = null) : AutoCloseable {
        var closeCount = 0
        override fun close() {
            closeCount += 1
            closeFailure?.let { throw it }
        }
    }

    @Test
    fun unsupportedDeviceUsesCpuAndRecordsReason() {
        val cpu = Resource("cpu")
        val reasons = mutableListOf<String>()
        val runtime = TrafficSignInferenceFallback({ cpu }, null, "GPU unsupported", reasons::add)
        assertSame(cpu, runtime.run { it })
        assertEquals("cpu", runtime.executionBackend)
        assertEquals(listOf("GPU unsupported"), reasons)
        runtime.close()
        runtime.close()
        assertEquals(1, cpu.closeCount)
    }

    @Test
    fun missingGpuNativeLibraryFallsBackDuringInitialization() {
        val cpu = Resource("cpu")
        val runtime = TrafficSignInferenceFallback(
            { cpu }, { throw UnsatisfiedLinkError("GPU library unavailable") }, null,
        )
        assertSame(cpu, runtime.run { it })
        assertEquals("cpu", runtime.executionBackend)
        assertTrue(requireNotNull(runtime.accelerationFallbackReason).contains("GPU library unavailable"))
        runtime.close()
    }

    @Test
    fun failedGpuInvocationReleasesGpuAndRetriesExactlyOnceOnCpu() {
        val gpu = Resource("gpu")
        val cpu = Resource("cpu")
        val calls = mutableListOf<String>()
        val runtime = TrafficSignInferenceFallback({ cpu }, { gpu }, null)
        val result = runtime.run {
            calls += it.name
            if (it === gpu) throw IllegalStateException("device lost")
            "recognized"
        }
        assertEquals("recognized", result)
        assertEquals(listOf("gpu", "cpu"), calls)
        assertEquals(1, gpu.closeCount)
        assertEquals("cpu", runtime.executionBackend)
        assertSame(cpu, runtime.run { it })
        runtime.close()
        assertEquals(1, cpu.closeCount)
    }

    @Test
    fun cpuFailureIsNotRetriedAndFailedCpuCreationDoesNotDoubleCloseGpu() {
        val gpu = Resource("gpu")
        val failure = IllegalStateException("CPU unavailable")
        var cpuCreations = 0
        val runtime = TrafficSignInferenceFallback(
            createCpu = { cpuCreations += 1; throw failure },
            createAccelerated = { gpu }, unavailableReason = null,
        )
        assertSame(failure, assertThrows(IllegalStateException::class.java) {
            runtime.run<Unit> { throw IllegalStateException("GPU invocation failed") }
        })
        runtime.close()
        assertEquals(1, cpuCreations)
        assertEquals(1, gpu.closeCount)
    }

    @Test
    fun gpuTeardownFailureStillAllowsCpuRecovery() {
        val gpu = Resource("gpu", IllegalStateException("GPU cleanup failed"))
        val cpu = Resource("cpu")
        val runtime = TrafficSignInferenceFallback({ cpu }, { gpu }, null)
        assertEquals("cpu", runtime.run {
            if (it === gpu) throw IllegalStateException("GPU device lost")
            it.name
        })
        assertTrue(requireNotNull(runtime.accelerationFallbackReason).contains("GPU cleanup failed"))
        runtime.close()
        assertEquals(1, gpu.closeCount)
        assertEquals(1, cpu.closeCount)
    }

    @Test
    fun nativeResourcesCannotRunOrCloseOnAnotherThread() {
        val gpu = Resource("gpu")
        val runtime = TrafficSignInferenceFallback({ Resource("cpu") }, { gpu }, null)
        var runFailure: Throwable? = null
        var closeFailure: Throwable? = null
        Thread {
            runFailure = runCatching { runtime.run { it.name } }.exceptionOrNull()
            closeFailure = runCatching { runtime.close() }.exceptionOrNull()
        }.apply { start(); join() }
        assertTrue(runFailure is IllegalStateException)
        assertTrue(closeFailure is IllegalStateException)
        assertEquals(0, gpu.closeCount)
        assertEquals("gpu", runtime.run { it.name })
        runtime.close()
        assertEquals(1, gpu.closeCount)
    }
}
