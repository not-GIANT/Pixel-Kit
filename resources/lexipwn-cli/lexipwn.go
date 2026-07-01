/*
  lexipwn (CLI version)

  Can do the following on Google Pixel 6 and up to Pixel 9 (requires root access):

  - manipulate devinfo partition (IMEIs, MACs, DSN, PSN, SKU etc)
  - fix IMEI SHA (the bootmode PS tag needs to be set to factory)
  - generate random but valid IMEIs based on the TAC/prefix
  - run arbitrary AT commands on the modem
  
  Usage: lexipwn [subcommand] [params]

  Available subcommands:

  * listps - list all tags in the PS tag area (TSV format)
  * setpsval [name1] [value1] [name2] [value2] ... - set tag values in the PS tag area
  * setpstype [name] [DIUS|DIFR] - set a tag type in the PS tag area
  * fiximeisha - actualize the IMEI SHA string in the persist partition
    (requires to be booted into the factory mode)
  * genimei [prefix] - generate a random valid IMEI starting with [prefix]
    (doesn't write this IMEI anywhere, so can be used without root)
  * atcmd [command] - run a single-line AT command and output its result

  Build with:

  GOOS=linux GOARCH=arm64 go build -a -trimpath -gcflags=all="-l -B -e" -ldflags "-s -w"
  (the result will be static; for dynamic PIE aarch64 builds, use GOOS=android instead)

  Created by Luxferre in 2024-2025, released into public domain
*/

package main

import (
  "os"
  "bytes"
  "encoding/binary"
  "fmt"
  "io"
  "strings"
  "strconv"
  "math/rand"
  "time"
)

/* a structure to describe a single tag in the PS or PSENV section */
type DevInfoTag struct {
  Type        [4]byte /* DIUS or DIFR */
  FullLength  uint32  /* name length + value length */
  NameLength  uint32
  Name        []byte
  Value       []byte
}

/* a structure to describe the entire devinfo partition image */
/* note that the unused areas might actually be used by the device */
type DevInfoImage struct {
  Magic           [4]byte /* must be DEVI */
  VerMajor        uint16
  VerMinor        uint16
  UnusedArea1     [32]byte
  BoardProject    uint16
  BoardStageCode  uint8
  BoardRevHi      uint8
  BoardRevLo      uint8
  BoardVariant    uint8
  SlotARetryCount uint8
  SlotAFlags      uint8
  SlotBRetryCount uint8
  SlotBFlags      uint8
  UnusedArea2     [74]byte
  PStags          []DevInfoTag
  PSENVtags       []DevInfoTag
}

/* info area byte offsets */
const offs_SlotARetryCount = 48
const offs_SlotBRetryCount = 52
const offs_PStags = 128
const offs_PSENVtags = 4096

/* read the file data into the DevInfoImage structure */
func readDevInfo(data []byte) DevInfoImage {
  r := bytes.NewReader(data)
  var info DevInfoImage
  /* read the header area */
  binary.Read(r, binary.BigEndian, &info.Magic)
  binary.Read(r, binary.LittleEndian, &info.VerMajor)
  binary.Read(r, binary.LittleEndian, &info.VerMinor)
  binary.Read(r, binary.BigEndian, &info.UnusedArea1)
  binary.Read(r, binary.LittleEndian, &info.BoardProject)
  binary.Read(r, binary.LittleEndian, &info.BoardStageCode)
  binary.Read(r, binary.LittleEndian, &info.BoardRevHi)
  binary.Read(r, binary.LittleEndian, &info.BoardRevLo)
  binary.Read(r, binary.LittleEndian, &info.BoardVariant)
  r.Seek(offs_SlotARetryCount, io.SeekStart)
  binary.Read(r, binary.LittleEndian, &info.SlotARetryCount)
  binary.Read(r, binary.LittleEndian, &info.SlotAFlags)
  r.Seek(offs_SlotBRetryCount, io.SeekStart)
  binary.Read(r, binary.LittleEndian, &info.SlotBRetryCount)
  binary.Read(r, binary.LittleEndian, &info.SlotBFlags)
  binary.Read(r, binary.BigEndian,    &info.UnusedArea2)
  /* read the PS and PSENV tag areas */
  info.PStags = make([]DevInfoTag, 0)
  info.PSENVtags = make([]DevInfoTag, 0)
  for {
    var tag DevInfoTag
    err := binary.Read(r, binary.BigEndian, &tag.Type)
    if err != nil {
      break
    }
    binary.Read(r, binary.LittleEndian, &tag.FullLength)
    binary.Read(r, binary.LittleEndian, &tag.NameLength)
    if tag.FullLength > 0 {
      if tag.NameLength > 0 {
        tag.Name = make([]byte, tag.NameLength)
        binary.Read(r, binary.BigEndian, &tag.Name)
      }
      tag.Value = make([]byte, tag.FullLength - tag.NameLength)
      binary.Read(r, binary.BigEndian, &tag.Value)
    }
    /* handle edge cases and populate the slices */
    if tag.FullLength < 0xf00 && tag.NameLength > 0 {
      curpos, _ := r.Seek(0, io.SeekCurrent)
      if curpos < offs_PSENVtags {
        info.PStags = append(info.PStags, tag)
      } else {
        info.PSENVtags = append(info.PSENVtags, tag)
      }
    }
  }
  return info
}

/* write the DevInfoImage structure into 8192 bytes of data */
func writeDevInfo(info DevInfoImage) []byte {
  buf := new(bytes.Buffer)
  buf.Grow(8192)
  /* write the header area */
  binary.Write(buf, binary.BigEndian, info.Magic)
  binary.Write(buf, binary.LittleEndian, info.VerMajor)
  binary.Write(buf, binary.LittleEndian, info.VerMinor)
  binary.Write(buf, binary.BigEndian, info.UnusedArea1)
  binary.Write(buf, binary.LittleEndian, info.BoardProject)
  binary.Write(buf, binary.LittleEndian, info.BoardStageCode)
  binary.Write(buf, binary.LittleEndian, info.BoardRevHi)
  binary.Write(buf, binary.LittleEndian, info.BoardRevLo)
  binary.Write(buf, binary.LittleEndian, info.BoardVariant)
  binary.Write(buf, binary.LittleEndian, uint16(0)) /* write two zeros */
  binary.Write(buf, binary.LittleEndian, info.SlotARetryCount)
  binary.Write(buf, binary.LittleEndian, info.SlotAFlags)
  binary.Write(buf, binary.LittleEndian, uint16(0)) /* write two zeros again */
  binary.Write(buf, binary.LittleEndian, info.SlotBRetryCount)
  binary.Write(buf, binary.LittleEndian, info.SlotBFlags)
  binary.Write(buf, binary.BigEndian, info.UnusedArea2)
  /* write the PS tag area */
  var curoffs uint32 = offs_PStags
  for _, tag := range info.PStags {
    binary.Write(buf, binary.BigEndian, tag.Type)
    binary.Write(buf, binary.LittleEndian, tag.FullLength)
    binary.Write(buf, binary.LittleEndian, tag.NameLength)
    if tag.FullLength > 0 {
      if tag.NameLength > 0 {
        binary.Write(buf, binary.BigEndian, tag.Name)
      }
      binary.Write(buf, binary.BigEndian, tag.Value)
    }
    curoffs += 12 + tag.FullLength
  }
  /* write the last pseudo-tag of the section */
  binary.Write(buf, binary.BigEndian, []byte("DIFR"))
  binary.Write(buf, binary.LittleEndian, uint32(offs_PSENVtags - curoffs - 12))
  /* fill in the zeros before the PSENV section */
  skip := int(offs_PSENVtags - curoffs - 8)
  for i:=0; i<skip; i++ {
    binary.Write(buf, binary.LittleEndian, uint8(0))
  }
  /* write the PSENV tag area */
  curoffs = offs_PSENVtags
  for _, tag := range info.PSENVtags {
    binary.Write(buf, binary.BigEndian, tag.Type)
    binary.Write(buf, binary.LittleEndian, tag.FullLength)
    binary.Write(buf, binary.LittleEndian, tag.NameLength)
    if tag.FullLength > 0 {
      if tag.NameLength > 0 {
        binary.Write(buf, binary.BigEndian, tag.Name)
      }
      binary.Write(buf, binary.BigEndian, tag.Value)
    }
    curoffs += 12 + tag.FullLength
  }
  /* write the last pseudo-tag of the section */
  binary.Write(buf, binary.BigEndian, []byte("DIFR"))
  skip = int(8184 - curoffs)
  binary.Write(buf, binary.LittleEndian, uint32(skip - 4))
  for i:=0; i<skip; i++ {
    binary.Write(buf, binary.LittleEndian, uint8(0))
  }
  return buf.Bytes()
}

/* set a string tag value (null-terminated) */
func setStringTag(tag *DevInfoTag, val string) {
  tag.Value = append([]byte(val), byte(0))
  tag.FullLength = tag.NameLength + uint32(len(tag.Value))
}

/* find the tag index in a slice (by name), return -1 if not found */
func findTag(tags []DevInfoTag, name string) int {
  bname := append([]byte(name), byte(0)) /* null-terminated tag name */
  for idx, tag := range tags {
    if bytes.Equal(tag.Name, bname) {
      return idx /* found the tag index, return it */
    }
  }
  return -1 /* no tag found with this name */
}

/* calculate Luhn checksum over 14 IMEI digits */
func calcLuhn(num string) int {
  sum := 0
  dd := 0
  for i, d := range num {
    if d >= 48 && d < 58 {
      dd = int(d) - 48
      if i%2 == 1 {
        dd += dd
        if dd > 9 {
          dd -= 9
        }
      }
      sum += dd
    }
  }
  sum %= 10
  if sum != 0 {
    sum = 10 - sum
  }
  return sum
}

/* run a single AT command and attempt to read its result */
func runAtCmd(cmd string) string {
  ifacefile := "/dev/umts_router"
  rcmd := append([]byte(cmd), byte(13), byte(10)) /* add CRLF */
  err := os.WriteFile(ifacefile, rcmd, 0666) /* write the request */
  if err != nil {
    panic(err)
  }
  data, err := os.ReadFile(ifacefile) /* read the response */
  if err != nil {
    panic(err)
  }
  return string(data)
}

/* entry point */
func main() {
  params := os.Args[1:]
  subcmd := params[0]
  fname := "/dev/block/bootdevice/by-name/devinfo"
  var info DevInfoImage
  /* preread the data if the subcommand is devinfo-related */
  if subcmd == "listps" || subcmd == "setpsval" || subcmd == "setpstype" {
    data, err := os.ReadFile(fname)
    if err != nil {
      panic(err)
    }
    info = readDevInfo(data)
  }
  /* execute the subcommand */
  switch subcmd {
    case "listps":
      for _, tag := range info.PStags {
        fmt.Printf("%s\t%s\t%s\n", tag.Type, tag.Name, tag.Value)
      }
    case "setpsval":
      valpairs := params[1:]
      plen := len(valpairs)
      if plen % 2 == 1 {
        fmt.Println("invalid parameter count!")
        return
      }
      for i := 0; i < plen; i+=2 {
        tagidx := findTag(info.PStags, valpairs[i])
        if tagidx > -1 {
          setStringTag(&info.PStags[tagidx], valpairs[i+1])
        }
      }
      os.WriteFile(fname, writeDevInfo(info), 0644)
      fmt.Println("devinfo image saved")
    case "setpstype":
      if len(params) != 3 {
        println("invalid parameter count!")
        return
      }
      tagtype := params[2]
      tagidx := findTag(info.PStags, params[1])
      if tagidx > -1 {
        if tagtype != "DIFR" { /* only two types are allowed, force DIUS unless it's DIFR */
          tagtype = "DIUS"
        }
        copy(info.PStags[tagidx].Type[:], []byte(tagtype))
        os.WriteFile(fname, writeDevInfo(info), 0644)
        fmt.Println("devinfo image saved")
      }
    case "genimei":
      rand.Seed(time.Now().UTC().UnixNano())
      var imeisb strings.Builder
      imeisb.WriteString(params[1]) /* start with the prefix */
      for i:=0; i < 14; i++ {
        imeisb.WriteString(strconv.Itoa(rand.Intn(10)))
      }
      imei := imeisb.String()[:14] /* only take the first 14 digits of the result */
      fmt.Printf("%s", imei + strconv.Itoa(calcLuhn(imei)))
    case "atcmd":
      if len(params) != 2 {
        println("invalid parameter count!")
        return
      }
      fmt.Printf("%s\n", runAtCmd(params[1]))
    case "fiximeisha":
      rawsharesult := runAtCmd("AT+GOOGGETIMEISHA")
      sharesult := strings.Split(strings.ReplaceAll(rawsharesult, "\r\n", "\n"), "\n")
      if len(sharesult) > 2 {
        if sharesult[2] == "ERROR" {
          fmt.Println("Error getting IMEI SHA, are you booted into the factory mode?")
        } else {
          shaparts := strings.Split(sharesult[2], ":")
          if len(shaparts) > 1 {
            targetfile := "/mnt/vendor/persist/modem/cpsha"
            os.WriteFile(targetfile, []byte(shaparts[1]), 0644)
            fmt.Println("CPSHA file written")
          }
        }
      }
    default:
      fmt.Println("Valid subcommands: listps, setpsval, setpstype, fiximeisha, genimei, atcmd")
  }
}

