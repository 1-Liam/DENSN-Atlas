package redislock

import (
    "context"
    "errors"
    "strconv"
    "time"
)

var (
    // ErrNotObtained is returned when a lock cannot be obtained.
    ErrNotObtained = errors.New("redislock: not obtained")

    // ErrLockNotHeld is returned when trying to release an inactive lock.
    ErrLockNotHeld = errors.New("redislock: lock not held")
)

// Obtain tries to obtain a new lock using a key with the given TTL.
// May return ErrNotObtained if not successful.
func (c *Client) Obtain(ctx context.Context, key string, ttl time.Duration, opt *Options) (*Lock, error) {
    return c.ObtainMulti(ctx, []string{key}, ttl, opt)
}

// Refresh extends the lock with a new TTL.
// May return ErrNotObtained if refresh is unsuccessful.
func (l *Lock) Refresh(ctx context.Context, ttl time.Duration, opt *Options) error {
    if l == nil {
        return ErrNotObtained
    }
    ttlVal := strconv.FormatInt(int64(ttl/time.Millisecond), 10)
    _, err := luaRefresh.Run(ctx, l.client, l.keys, l.value, ttlVal).Result()
    if err != nil {
        if errors.Is(err, redis.Nil) {
            return ErrNotObtained
        }
        return err
    }
    return nil
}

// Release manually releases the lock.
// May return ErrLockNotHeld.
func (l *Lock) Release(ctx context.Context) error {
    if l == nil {
        return ErrLockNotHeld
    }
    _, err := luaRelease.Run(ctx, l.client, l.keys, l.value).Result()
    if err != nil {
        if errors.Is(err, redis.Nil) {
            return ErrLockNotHeld
        }
        return err
    }
    return nil
}

func Example() {
    // Try to obtain lock.
    lock, err := locker.Obtain(ctx, "my-key", 100*time.Millisecond, nil)
    if err == redislock.ErrNotObtained {
        fmt.Println("Could not obtain lock!")
        return
    }

    // Don't forget to defer Release.
    defer lock.Release(ctx)
    fmt.Println("I have a lock!")

    // Extend my lock.
    if err := lock.Refresh(ctx, 100*time.Millisecond, nil); err != nil {
        log.Fatalln(err)
    }

    // Output:
    // I have a lock!
    // Yay, I still have my lock!
    // Now, my lock has expired!
}

func TestLock_Refresh(t *testing.T) {
    lock := quickObtain(t, rc, lockKey, time.Hour)
    defer lock.Release(ctx)

    if err := lock.Refresh(ctx, time.Minute, nil); err != nil {
        t.Fatal(err)
    }
}

func TestLock_Refresh_expired(t *testing.T) {
    lock := quickObtain(t, rc, lockKey, 5*time.Millisecond)
    defer lock.Release(ctx)

    time.Sleep(10 * time.Millisecond)
    if exp, got := ErrNotObtained, lock.Refresh(ctx, time.Minute, nil); !errors.Is(got, exp) {
        t.Fatalf("expected %v, got %v", exp, got)
    }
}

func TestLock_Release_expired(t *testing.T) {
    lock := quickObtain(t, rc, lockKey, 5*time.Millisecond)
    defer lock.Release(ctx)

    time.Sleep(10 * time.Millisecond)
    if exp, got := ErrLockNotHeld, lock.Release(ctx); !errors.Is(got, exp) {
        t.Fatalf("expected %v, got %v", exp, got)
    }
}
