// Extracted from go-redsync/redsync at commit 7a6f793e6fdad02673681d67bac13a1f04c9c7de.
// Sources:
// - mutex.go
// - mutex_test.go
// - error.go
//
// This excerpt is kept only as provenance evidence for the real-world
// evaluation bundle.

package redsync

// ErrExtendFailed is the error resulting if Redsync fails to extend the
// lock.
var ErrExtendFailed = errors.New("redsync: failed to extend lock")

// ExtendContext resets the mutex's expiry and returns the status of expiry extension.
func (m *Mutex) ExtendContext(ctx context.Context) (bool, error) {
	start := time.Now()
	n, err := m.actOnPoolsAsync(func(pool redis.Pool) (bool, error) {
		return m.touch(ctx, pool, m.value, int(m.expiry/time.Millisecond))
	})
	if n < m.quorum {
		return false, err
	}
	now := time.Now()
	until := now.Add(m.expiry - now.Sub(start) - time.Duration(int64(float64(m.expiry)*m.driftFactor)))
	if now.Before(until) {
		m.until = until
		return true, nil
	}
	return false, ErrExtendFailed
}

func (m *Mutex) touch(ctx context.Context, pool redis.Pool, value string, expiry int) (bool, error) {
	touchScript := touchScript
	if m.setNXOnExtend {
		touchScript = touchWithSetNXScript
	}
	status, err := conn.Eval(touchScript, m.name, value, expiry)
	if err != nil {
		return false, err
	}
	return status != int64(0), nil
}

func TestMutexExtend(t *testing.T) {
	// mutex.Extend() should refresh expiry while the lock is still valid.
}

func TestMutexExtendExpired(t *testing.T) {
	// mutex.Extend() should fail after expiry.
}

func TestSetNXOnExtendFailsToAcquireLockWhenKeyIsTaken(t *testing.T) {
	// mutex.Extend() should fail when another owner has taken the key.
}
